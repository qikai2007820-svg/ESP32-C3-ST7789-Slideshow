#include <Arduino_GFX_Library.h>
#include <SD.h>
#include <SPI.h>

/* 接线定义 */
#define SCK_PIN  4
#define MOSI_PIN 6
#define MISO_PIN 5
#define LCD_CS   7
#define LCD_DC   2
#define SD_CS    10
#define BL_PIN   3   // 背光 PWM 引脚
#define LED_PIN  8   // 板载 LED（低电平点亮）


/* 幻灯片参数 */
#define SLIDE_INTERVAL_MS 3000   // 每张停留时间（毫秒）
#define MAX_FILES         99     // 文件编号上限

// 分块显示：240x120 像素 = 86,400 字节
const size_t CHUNK_SIZE = 240 * 120 * 3;
uint8_t *buffer;

/* 总线与屏幕驱动 */
Arduino_DataBus *bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, SCK_PIN, MOSI_PIN, MISO_PIN);
Arduino_ST7789  *gfx = new Arduino_ST7789(bus, -1 /* RST已接3.3V */, GFX_NOT_DEFINED, true);

/* 幻灯片状态 */
int  currentIndex  = 1;          // 当前尝试的文件编号（1-99）
bool firstDraw     = true;       // 第一次不等待计时器
unsigned long lastDrawTime = 0;  // 上一次成功显示的时间戳

// ─────────────────────────────────────────────
//  构造形如 "/01.bin" 的路径
// ─────────────────────────────────────────────
void buildPath(char *buf, int index) {
  char num[4];
  snprintf(num, sizeof(num), "%02d", index);
  strcpy(buf, "/");
  strcat(buf, num);
  strcat(buf, ".bin");
}

// ─────────────────────────────────────────────
//  尝试显示指定路径的 bin 文件
//  返回 true = 成功，false = 文件缺失或读取异常
// ─────────────────────────────────────────────
bool drawFullImage(const char *path) {
  File file = SD.open(path);
  if (!file) {
    Serial.print("Skip (not found): ");
    Serial.println(path);
    return false;
  }

  // 文件大小校验（可选：确保是完整的 172800 字节）
  if (file.size() != (size_t)(CHUNK_SIZE * 2)) {
    Serial.print("Skip (bad size): ");
    Serial.println(path);
    file.close();
    return false;
  }

  // ST7789 240x240 屏幕旋转 180 度后，Y 轴会产生 80 像素的硬件偏移 (320 - 240 = 80)
  int y_offset = 80;

  // --- 上半屏 (Y: 0-119) ---
  if (file.read(buffer, CHUNK_SIZE) != CHUNK_SIZE) {
    Serial.println("Read error (top half)");
    file.close();
    return false;
  }
  bus->beginWrite();
  gfx->writeAddrWindow(0, 0 + y_offset, 240, 120);
  bus->writeBytes(buffer, CHUNK_SIZE);
  bus->endWrite();

  // --- 下半屏 (Y: 120-239) ---
  if (file.read(buffer, CHUNK_SIZE) != CHUNK_SIZE) {
    Serial.println("Read error (bottom half)");
    file.close();
    return false;
  }
  bus->beginWrite();
  gfx->writeAddrWindow(0, 120 + y_offset, 240, 120);
  bus->writeBytes(buffer, CHUNK_SIZE);
  bus->endWrite();

  file.close();

  Serial.print("Displayed: ");
  Serial.println(path);
  return true;
}

// ─────────────────────────────────────────────
//  从 startIndex 开始扫描，找下一张有效文件
//  找到则显示并返回其编号；全部失败则返回 -1
// ─────────────────────────────────────────────
int findAndDraw(int startIndex) {
  char path[16];
  for (int tried = 0; tried < MAX_FILES; tried++) {
    int idx = (startIndex - 1 + tried) % MAX_FILES + 1;  // 循环 1-99
    buildPath(path, idx);
    if (drawFullImage(path)) {
      return idx;   // 成功，返回当前编号
    }
  }
  return -1;  // 99 个全部失败
}

// ─────────────────────────────────────────────
//  setup
// ─────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // 1. 申请 DMA 内存
  buffer = (uint8_t *)heap_caps_malloc(CHUNK_SIZE, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
  if (!buffer) { Serial.println("Malloc Failed!"); while (1); }

  // 2. 初始化屏幕
  gfx->begin();
  gfx->fillScreen(0x0000);

  // 3. 强制 18-bit (RGB666) 模式 + 修正扫描方向（防镜像）
  bus->beginWrite();
  bus->writeCommand(0x3A);  // 色彩格式：18-bit
  bus->write(0x06);
  bus->writeCommand(0x36);  // MADCTL：扫描方向
  bus->write(0xC0);         // MY=1, MX=1 → 旋转 180 度
  bus->endWrite();

  // 4. 初始化 SD 卡
  if (!SD.begin(SD_CS)) { Serial.println("SD Failed!"); while (1); }

  // 5. 背光 PWM 初始化（ESP32 core 3.x 新版 API）
  //    duty 77 / 255 ≈ 30% 亮度
  ledcAttach(BL_PIN, 5000, 8);   // 绑定引脚，5 kHz，8-bit 分辨率
  ledcWrite(BL_PIN, 77);         // 设置占空比

  Serial.println("System Ready. Starting slideshow...");
}

// ─────────────────────────────────────────────
//  loop — 非阻塞幻灯片
// ─────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // 第一帧立刻显示；之后等满 SLIDE_INTERVAL_MS
  if (!firstDraw && (now - lastDrawTime < SLIDE_INTERVAL_MS)) {
    return;
  }

  // 计算下一张编号（第一帧从 1 开始，之后 +1）
  int nextIndex = firstDraw ? 1 : (currentIndex % MAX_FILES) + 1;
  firstDraw = false;

  int result = findAndDraw(nextIndex);
  if (result == -1) {
    // SD 卡上没有任何有效的 .bin 文件
    Serial.println("No valid files found. Halting slideshow.");
    gfx->fillScreen(0x0000);
    while (1) delay(1000);   // 停止
  }

  currentIndex = result;
  lastDrawTime = millis();   // 记录本次显示完成时刻
}
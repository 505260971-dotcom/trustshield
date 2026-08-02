/* TrustShield 路演PPT 导出脚本
 * 1) 10 页全部导出 16:9 高清 PNG（2x，3840×2160）
 * 2) 第 5 页（流程图动画）、第 6 页（截图轮播）导出 GIF 动图
 * 用法: node export.cjs
 */
const { chromium } = require('C:/Users/chengtx/Desktop/contractguard/frontend/node_modules/playwright-core')
const { GIFEncoder, quantize, applyPalette } = require('gifenc')
const { PNG } = require('pngjs')
const path = require('path')
const fs = require('fs')

const HTML = 'C:/Users/chengtx/Desktop/contractguard/docs/03-演示与交付/信盾-路演PPT-v2.html'
const OUT = __dirname
const W = 1920, H = 1080
const EXE = path.join(process.env.LOCALAPPDATA, 'ms-playwright/chromium-1228/chrome-win64/chrome.exe')

const NAMES = [
  '01-封面', '02-问题与痛点', '03-组织架构', '04-创新空间', '05-结果可验证性-主流程',
  '06-可视化演示-截图', '07-数据适配能力', '08-AI-Agent-技术完成度', '09-结果可验证性-数据', '10-结语',
]
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function setupPage(ctx) {
  const page = await ctx.newPage()
  await page.setViewportSize({ width: W, height: H })
  await page.goto('file:///' + HTML.replace(/\\/g, '/'), { waitUntil: 'load' })
  await page.evaluate(() => document.fonts.ready)
  await page.evaluate(() => {
    // 隐藏演示器 UI（右侧圆点导航、页码），只留幻灯片本体
    document.getElementById('dots').style.display = 'none'
    document.getElementById('count').style.display = 'none'
  })
  await sleep(400)
  return page
}

async function main() {
  const browser = await chromium.launch({ executablePath: EXE, headless: true })
  fs.mkdirSync(OUT, { recursive: true })

  /* ---- Pass A: 静态高清 PNG（2x，动画页除外，只出动图） ---- */
  const ctxA = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 2 })
  const pageA = await setupPage(ctxA)
  for (let i = 0; i < NAMES.length; i++) {
    if (i === 4 || i === 5) continue // 第 5、6 页只导出 GIF
    await pageA.evaluate((k) => show(k), i)
    await sleep(1200) // 覆盖页面过渡 .4s + .anim 最大延迟 .42s + 过渡 .55s
    await pageA.screenshot({ path: path.join(OUT, `slide-${NAMES[i]}.png`) })
    console.log('PNG ok:', NAMES[i])
  }
  await ctxA.close()

  /* ---- Pass B: 动画页逐帧截图（1x） ---- */
  const ctxB = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 })
  const pageB = await setupPage(ctxB)
  const frameDir = path.join(OUT, '_frames'); fs.mkdirSync(frameDir, { recursive: true })

  // 第 5 页: 流程图，8 节点 × 1.3s 点亮 + 2.4s 停留 → 截 12.6s @10fps
  // 先等切页过渡与 .anim 入场完全结束（页面静止），再从零启动流程动画，开头不带切页效果
  await pageB.evaluate(() => show(4))
  await sleep(1500)
  await pageB.evaluate(() => { clearInterval(FLOW.timer); FLOW.playing = false; FLOW.cur = -1; flowRender(); flowPlay() })
  const flowDir = path.join(frameDir, 'flow'); fs.mkdirSync(flowDir, { recursive: true })
  for (let k = 0; k < 126; k++) {
    const t0 = Date.now()
    await pageB.screenshot({ path: path.join(flowDir, String(k + 1).padStart(4, '0') + '.png') })
    const el = Date.now() - t0
    if (100 - el > 0) await sleep(100 - el)
  }
  console.log('flow frames done')

  // 第 6 页: 轮播，5 张 × 4.5s + 0.6s 淡入 → 截一个完整轮次(24s) @5fps
  await pageB.evaluate(() => show(5))
  await sleep(1500)
  await pageB.evaluate(() => { clearInterval(GALLERY.timer); galleryGo(0); restartGallery() })
  const galDir = path.join(frameDir, 'gallery'); fs.mkdirSync(galDir, { recursive: true })
  for (let k = 0; k < 120; k++) {
    const t0 = Date.now()
    await pageB.screenshot({ path: path.join(galDir, String(k + 1).padStart(4, '0') + '.png') })
    const el = Date.now() - t0
    if (200 - el > 0) await sleep(200 - el)
  }
  console.log('gallery frames done')
  await ctxB.close()
  await browser.close()

  /* ---- 合成 GIF（gifenc 纯 JS 编码，逐帧量化） ---- */
  function toGif(dir, frameCount, delayMs, outName) {
    const gif = GIFEncoder()
    for (let k = 1; k <= frameCount; k++) {
      const png = PNG.sync.read(fs.readFileSync(path.join(dir, String(k).padStart(4, '0') + '.png')))
      const rgba = new Uint8Array(png.data) // RGBA8888
      const palette = quantize(rgba, 256)
      const index = applyPalette(rgba, palette)
      gif.writeFrame(index, png.width, png.height, { palette, delay: delayMs, loop: 0 })
      if (k % 40 === 0) console.log('gif frames:', k, '/', frameCount)
    }
    gif.finish()
    const out = path.join(OUT, outName)
    fs.writeFileSync(out, gif.bytes())
    console.log('GIF ok:', outName, Math.round(fs.statSync(out).size / 1024) + 'KB')
  }
  toGif(flowDir, 126, 100, 'slide-05-结果可验证性-主流程-动画.gif')
  toGif(galDir, 120, 200, 'slide-06-可视化演示-截图-动画.gif')

  // Windows 上文件句柄可能延迟释放，重试几次确保清理干净
  for (let i = 0; i < 5; i++) {
    try { fs.rmSync(frameDir, { recursive: true, force: true }); break }
    catch { await sleep(600) }
  }
  console.log('done')
}

main().catch((e) => { console.error(e); process.exit(1) })

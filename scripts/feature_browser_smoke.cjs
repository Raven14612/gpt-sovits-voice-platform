// Explicit real feature extraction; no training button is clicked.
const { chromium, expect } = require('playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const dataset = process.env.FEATURE_DATASET_NAME;
  if (!dataset) throw new Error('Set FEATURE_DATASET_NAME to an already reviewed, authorized dataset.');
  const directory = path.resolve(__dirname, '../data/logs/diagnostics/features');
  await fs.mkdir(directory, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(process.env.FEATURE_SMOKE_URL || 'http://127.0.0.1:7860');
    await page.getByRole('button', {name:'音色训练与仓库',exact:true}).click();
    await page.getByRole('listbox', {name:'待训练数据集',exact:true}).click();
    await page.getByRole('option', {name:dataset,exact:true}).click();
    const button = page.getByRole('button', {name:'提取特征（不训练）',exact:true});
    await expect(button).toBeEnabled();
    await button.click();
    const status = page.getByRole('textbox', {name:'任务状态',exact:true});
    await expect(status).toHaveValue(/状态：执行中/, {timeout:20000});
    await expect(button).toBeDisabled();
    await page.screenshot({path:path.join(directory,'01-running.png'),fullPage:true});
    await expect(status).toHaveValue(/状态：(成功|失败)/, {timeout:300000});
    const final = await status.inputValue();
    if (!final.includes('状态：成功')) throw new Error(final);
    await expect(button).toBeEnabled();
    await expect(page.getByRole('textbox',{name:'特征状态',exact:true})).toHaveValue(/manifest.json/);
    await page.screenshot({path:path.join(directory,'02-success.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth+2)) throw new Error('Mobile overflow');
    await page.screenshot({path:path.join(directory,'03-mobile.png'),fullPage:true});
    if (errors.length) throw new Error(errors.join('\n'));
    await fs.writeFile(path.join(directory,'result.json'), JSON.stringify({status:final,errors,trainingStarted:false},null,2));
    console.log('FEATURE BROWSER PASS\n' + final);
  } catch(error) {
    await page.screenshot({path:path.join(directory,'failure.png'),fullPage:true});
    throw error;
  } finally { await browser.close(); }
}
main().catch(error => {console.error(error);process.exitCode=1;});

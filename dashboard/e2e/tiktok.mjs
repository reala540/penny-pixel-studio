// Real browser and video metadata against simulated services; no TikTok account is contacted.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BASE, WORKER, SUPABASE, openStudio, seed, startServer, withBrowser } from './harness.mjs';
const cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'content-type': 'application/json' };
const video = readFileSync(new URL('./fixtures/tiktok-preview.mp4', import.meta.url));
const snapshot = { variant_id: 'v-tt', account_id: 'acc-tt', account_external_id: 'creator-1', script_version_id: 'sv-1', title: 'Test video', body: 'Saved caption', hashtags: ['ai'], render: { scenes: [] }, preview_key: 'preview.mp4' };
function sample() {
  const db = seed();
  db.social_accounts = [{ id: 'acc-tt', platform: 'tiktok', label: 'TikTok', enabled: true, handle: 'Penny & Pixel', oauth_connections: { status: 'connected' } }];
  db.content_projects[0].recipe = { preview_key: 'preview.mp4' };
  db.script_versions = [{ id: 'sv-1', project_id: 'proj-1', version: 1, body: { title: 'Test video', hook: 'A test hook.', scenes: [], cta: '' } }];
  db.content_variants = [{ id: 'v-tt', project_id: 'proj-1', social_account_id: 'acc-tt', kind: 'short_video', title: 'Test video', body: 'Saved caption', hashtags: ['ai'], tags: [], status: 'approved', social_accounts: { platform: 'tiktok', label: 'TikTok' }, scheduled_posts: [{ id: 'post-tt', status: 'scheduled', scheduled_at: new Date(Date.now()+86400000).toISOString() }] }];
  db.research_claims = []; db.thumbnails = [];
  return db;
}
const server = await startServer();
try {
 await withBrowser(async browser => {
  const db = sample();
  const {page, context, errors} = await openStudio(browser, '/', {db});
  page.setDefaultTimeout(15000);
  const confirms = [];
  await context.route(`${WORKER}/api/tiktok/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === 'OPTIONS') return route.fulfill({status:204,headers:cors});
    if (path.endsWith('/content')) return route.fulfill({headers:cors,body:JSON.stringify(snapshot)});
    if (path.endsWith('/creator')) return route.fulfill({headers:cors,body:JSON.stringify({account_id:'acc-tt',direct_post:true,creator_nickname:'Penny & Pixel',privacy_level_options:['PUBLIC_TO_EVERYONE','SELF_ONLY'],comment_disabled:false,duet_disabled:true,stitch_disabled:false,max_video_post_duration_sec:60,content_snapshot:snapshot})});
    const body=route.request().postDataJSON(); confirms.push(body);
    db.content_variants[0].scheduled_posts[0].tiktok_post={...body.choices,content_snapshot:structuredClone(body.content_snapshot),confirmed_at:new Date().toISOString()};
    return route.fulfill({headers:cors,body:JSON.stringify({ok:true})});
  });
  await context.route(`${SUPABASE}/storage/v1/object/sign/**`, route=>route.request().method()==='OPTIONS' ? route.fulfill({status:204,headers:cors}) : route.request().method()==='POST' ? route.fulfill({headers:cors,body:JSON.stringify({signedURL:'/object/sign/studio/preview.mp4?token=test'})}) : route.fulfill({contentType:'video/mp4',body:video}));
  await page.goto(`${BASE}/content/proj-1`);
  await page.getByRole('tab',{name:/Platform posts/}).click();
  const panel = page.getByRole('region',{name:'TikTok posting settings'});
  const button = panel.getByRole('button',{name:'Confirm and post at the scheduled time'});
  await button.waitFor();
  assert.equal(await button.isDisabled(),true);
  assert.equal(await panel.locator('select').inputValue(),'');
  assert.equal(await panel.getByLabel('Duet',{exact:false}).isDisabled(),true);
  await panel.locator('select').selectOption('SELF_ONLY');
  await panel.getByRole('checkbox',{name:/By posting/}).check();
  await page.waitForFunction(()=>document.querySelector('video')?.duration > 0);
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.includes('Confirm and post at the scheduled time')&&!b.disabled));
  console.log('PASS privacy, consent and actual preview metadata are required');
  await page.getByLabel('Caption',{exact:false}).first().fill('Unsaved caption');
  await page.getByText('Save the edited post below before confirming TikTok settings.',{exact:true}).waitFor();
  assert.equal(await button.isDisabled(),true); assert.equal(confirms.length,0);
  console.log('PASS unsaved caption cannot be confirmed');
  await page.getByLabel('Caption',{exact:false}).first().fill('Saved caption');
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.includes('Confirm and post at the scheduled time')&&!b.disabled));
  await button.click();
  await page.getByText('Confirmed: posts to',{exact:false}).waitFor();
  assert.equal(confirms.length,1); assert.deepEqual(confirms[0].content_snapshot,snapshot); assert.ok(confirms[0].seconds>0);
  console.log('PASS confirmation binds the saved content and real video duration');
  snapshot.render={scenes:[{text:'Different video'}]};
  await page.reload(); await page.getByRole('tab',{name:/Platform posts/}).click();
  await page.getByText('Confirm again after changing the video or caption.',{exact:true}).waitFor();
  assert.equal(await page.getByText('Confirmed: posts to',{exact:false}).count(),0);
  console.log('PASS a changed video requires fresh confirmation');
  db.content_variants[0].scheduled_posts[0].status='processing';
  await page.reload(); await page.getByRole('tab',{name:/Platform posts/}).click();
  await page.getByText('TikTok is processing this video.',{exact:false}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Confirm and post at the scheduled time'}).count(),0);
  assert.equal(await page.getByLabel('Caption',{exact:false}).first().isDisabled(),true);
  assert.deepEqual(errors,[]);
  console.log('PASS processing is visible and cannot be edited or submitted again');
  await context.close();
 });
} finally {server.kill();}

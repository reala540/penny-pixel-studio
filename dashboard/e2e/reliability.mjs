// Regression checks against simulated services only. Never connects to the live studio.
import {openStudio,startServer,withBrowser,seed} from './harness.mjs';
let failures=0;
async function test(name,fn){try{await fn();console.log(`PASS ${name}`);}catch(e){failures++;console.log(`FAIL ${name}: ${e.message}`);}}
const server=await startServer();
try{await withBrowser(async browser=>{
  await test('Failed idea settings never expose editable defaults', async()=>{
    const {page,context}=await openStudio(browser,'/settings/ideas',{fail:{settings:500}});
    await page.getByText("Couldn't load idea generation settings").waitFor();
    if(await page.getByRole('spinbutton').count())throw Error('Editable default count was exposed');
    await context.close();
  });
  await test('Unknown automation never promises manual approval',async()=>{
    const {page,context}=await openStudio(browser,'/settings/automation',{fail:{settings:500}});
    await page.getByText("Couldn't load automation settings").waitFor();
    if(await page.getByText('Every package waits for your approval.',{exact:true}).count())throw Error('False manual-approval reassurance');
    await context.close();
  });
  await test('Failed account schedules have Retry instead of a blank page',async()=>{
    const {page,context}=await openStudio(browser,'/settings/schedule',{fail:{social_accounts:500}});
    await page.getByText("Couldn't load account schedules").waitFor();
    if(!await page.getByRole('button',{name:'Retry',exact:true}).count())throw Error('No Retry');
    await context.close();
  });
  await test('Unknown timezone does not expose a fallback as saved',async()=>{
    const {page,context}=await openStudio(browser,'/settings/appearance',{fail:{settings:500}});
    await page.getByText("Couldn't load the timezone").waitFor();
    if(await page.getByRole('combobox',{name:'Timezone',exact:true}).count())throw Error('Unconfirmed timezone editable');
    await context.close();
  });
  await test('Home and Activity link to actual project progress',async()=>{
    const {page,context}=await openStudio(browser,'/');
    const link=page.getByRole('link',{name:'View progress',exact:true}).first();await link.waitFor();
    if(!((await link.getAttribute('href'))??'').includes('/content/proj-1'))throw Error('Wrong project destination');
    await page.getByRole('link',{name:'Activity',exact:true}).first().click();
    await page.getByRole('link',{name:'View progress',exact:true}).first().waitFor();
    await context.close();
  });
  await test('A creation draft recovers on a second device without queuing work',async()=>{
    const db=seed();db.generation_jobs=[];
    const first=await openStudio(browser,'/',{db});
    await first.page.evaluate(()=>localStorage.setItem('studio-create-drafts:00000000-0000-4000-8000-000000000001',JSON.stringify([{id:'cloud-draft',rev:1,updatedAt:new Date().toISOString(),step:'idea',channel:'ai',kind:null,ideaId:null,own:'How small shops can use AI',depth:3}])));
    await first.page.reload();
    for(let i=0;i<30&&!db.studio_drafts?.length;i++)await first.page.waitForTimeout(200);
    if(!db.studio_drafts?.length)throw Error('Draft was not uploaded');
    const second=await openStudio(browser,'/',{db});
    await second.page.getByRole('link',{name:'Continue',exact:true}).first().waitFor();
    await second.page.getByRole('link',{name:'Continue',exact:true}).first().click();
    await second.page.getByPlaceholder('Example: Three practical AI tools that save small shops time each week').waitFor();
    if(await second.page.getByPlaceholder('Example: Three practical AI tools that save small shops time each week').inputValue()!=='How small shops can use AI')throw Error('Typed brief was not recovered');
    if(db.generation_jobs.length)throw Error('Recovery queued new work');
    await first.context.close();await second.context.close();
  });
  await test('A Calendar deep link opens a post outside the current week',async()=>{
    const db=seed();db.generation_jobs=[];
    db.scheduled_posts=[{id:'future-post',status:'scheduled',scheduled_at:new Date(Date.now()+30*86400000).toISOString(),social_account_id:'acc-yt-ai',variant_id:'v-future',content_variants:{project_id:'proj-1',title:'Future publication',kind:'long_video',body:'Text'},social_accounts:{label:'YouTube AI',platform:'youtube'},published_posts:null}];
    const {page,context,errors}=await openStudio(browser,'/calendar?post=future-post',{db});
    await page.getByRole('heading',{name:'Future publication',exact:true}).waitFor();
    if(errors.length)throw Error(errors.join(';'));
    await context.close();
  });
  await test('Bulk approval reports successes separately from failures',async()=>{
    const db=seed();db.content_projects.push({...db.content_projects[0],id:'proj-2',title:'Another package'});
    const {page,context}=await openStudio(browser,'/content',{db});
    await context.route('https://mock-supabase.test/rest/v1/rpc/approve_project',route=>{
      const payload=JSON.parse(route.request().postData());
      return route.fulfill({status:payload.p_project_id==='proj-1'?200:400,headers:{'access-control-allow-origin':'*','content-type':'application/json'},body:payload.p_project_id==='proj-1'?'1':JSON.stringify({message:'This package changed elsewhere'})});
    });
    await page.getByRole('button',{name:'Approve all 2 that passed every check'}).click();
    await page.getByRole('dialog').getByRole('button',{name:'Approve 2',exact:true}).click();
    const results=page.getByRole('list',{name:'Approval results'});await results.waitFor();
    const text=await results.innerText();
    if(!text.includes('How to write better prompts for ChatGPT: Approved')||!text.includes('Another package: Not approved'))throw Error('Partial outcome was hidden');
    await context.close();
  });
  await test('Cancel work is scoped and retains the other request',async()=>{
    const db=seed();db.generation_jobs.push({...db.generation_jobs[0],id:'job-2'});
    const {page,context,calls}=await openStudio(browser,'/activity',{db});
    await page.getByRole('button',{name:'Cancel work',exact:true}).first().click();
    await page.getByRole('dialog').getByRole('button',{name:'Cancel work',exact:true}).click();
    await page.getByText('Stop requested.',{exact:false}).waitFor();
    if(!db.generation_jobs[0].cancel_requested_at||db.generation_jobs[1].cancel_requested_at)throw Error('Cancellation was not scoped');
    if(calls.some(x=>x.path==='worker:/api/stop-clear'))throw Error('Used global cancellation');
    await context.close();
  });
});}finally{server.kill();}
process.exitCode=failures?1:0;

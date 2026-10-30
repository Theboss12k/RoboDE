import {test,expect,type Page} from '@playwright/test';

test.use({storageState:{cookies:[],origins:[]}});
async function open(page:Page){
 await page.request.post('/login',{form:{code:'hosted-browser-test-code'}});
 await page.goto('/');
 await expect(page.getByLabel('Select project',{exact:true})).toHaveValue('apple_transfer');
}
async function models(page:Page,clarify=false){
 // A deterministic provider runs through the real custom LLM worker. No external inference or hardware.
 const task={id:'point',name:'Turn base',intent:'Set base yaw to 0.03 rad',operation:'command',robot_id:'arm_01',binding_status:'unresolved'};
 const proposal=clarify?{status:'needs_clarification',questions:['How many times should the robot wave?']}:{status:'ready',tasks:[task]};
 const converter={calls:[{function:'set_base_yaw',arguments:{value:.03,unit:'rad'}}]};
 const source=`async def invoke(input: str, system_prompt: str) -> str:\n    if 'PLANNER' in system_prompt:\n        return ${JSON.stringify(JSON.stringify(proposal))}\n    return ${JSON.stringify(JSON.stringify(converter))}\n`;
 const profiles=[];
 for(const name of ['Composer Planner','Composer Converter']){
  const result=await page.request.post('/api/llm/adapters',{data:{name,protocol:'python_function',connection_type:'custom',base_url:'http://127.0.0.1',model:name,source_code:source}});
  expect(result.ok(),await result.text()).toBeTruthy();profiles.push(await result.json());
 }
 const result=await page.request.put('/api/llm/roles',{data:{planner_adapter_id:profiles[0].id,binding_adapter_id:profiles[1].id,vision_enabled:false}});expect(result.ok()).toBeTruthy();
}

test('Generate plan invokes both roles, preserves edits and validates manual actuator calls',async({page})=>{
 await open(page);await models(page);
 const endpoint='/api/projects/apple_transfer/plan-definitions';
 const created=await(await page.request.post(endpoint,{data:{name:'Composer acceptance',goal:'Set base yaw to 0.03 rad with Atlas Arm 01'}})).json();
 const untouched=await(await page.request.post(endpoint,{data:{name:'Other plan',goal:'Leave this plan alone'}})).json();
 // Open the first definition through the tree rather than modifying another plan.
 await page.reload();await page.getByRole('button',{name:'Plans workspace',exact:true}).click();
 await page.getByRole('button',{name:/^Composer acceptance \d+$/}).click();
 const calls:string[]=[];page.on('request',r=>{if(r.method()==='POST'&&/\/(decompose|bind-commands)$/.test(r.url()))calls.push(r.url().split('/').at(-1)!)});
 const actions=page.getByLabel('Plan actions',{exact:true});
 await actions.getByRole('button',{name:'Generate plan',exact:true}).click();
 await expect(page.getByLabel('Task actuator commands')).toContainText('set_base_yaw(value=0.03, unit="rad")');
 expect(calls).toEqual(['decompose','bind-commands']);
 const generated=await(await page.request.get(`${endpoint}/${created.id}`)).json();
 expect(generated.inference_evidence.map((e:any)=>e.model)).toEqual(['Composer Planner','Composer Converter']);
 expect((await(await page.request.get(`${endpoint}/${untouched.id}`)).json()).tasks).toEqual([]);
 await expect(actions.getByRole('button',{name:'Regenerate plan',exact:true})).toBeDisabled();
 await page.getByLabel('Semantic task intent',{exact:true}).fill('Turn base gently');
 await expect(page.getByLabel('Task actuator commands')).not.toContainText('set_base_yaw(value=');
 await page.getByText('Add a command manually',{exact:true}).click();
 await page.getByLabel('Approved task function',{exact:true}).selectOption('set_base_yaw');
 await page.getByLabel('Function value',{exact:true}).fill('0.02');
 await page.getByRole('button',{name:'Add function call',exact:true}).click();
 await actions.getByRole('button',{name:'Validate plan',exact:true}).click();
 await expect(page.getByLabel('Validation progress')).toContainText('Check collisions · done');
 await expect(actions.getByRole('button',{name:'Run simulation',exact:true})).toBeEnabled();
 expect(calls.filter(c=>c==='decompose')).toHaveLength(1);
 const edited=await(await page.request.get(`${endpoint}/${created.id}`)).json();
 expect(edited.tasks[0].function_calls[0].arguments.value).toBe(.02);
 await page.screenshot({path:'artifacts/simple-workflow/plan-composer.png',animations:'disabled',fullPage:true});
 const goal=await page.getByLabel('Plan goal',{exact:true}).boundingBox(),buttons=await actions.boundingBox();
 expect(buttons!.y-(goal!.y+goal!.height)).toBeLessThan(140);
 await page.getByRole('button',{name:'Robot controls',exact:true}).click();
 await expect(page.getByLabel('Robot transform mode')).toBeVisible();
 const panel=page.getByRole('region',{name:'Robot virtual controls',exact:true});
 await expect(panel.getByText('Connected · simulated feedback',{exact:true})).toBeVisible();
 const closed=page.waitForResponse(r=>r.request().method()==='DELETE'&&/\/api\/controls\//.test(r.url()));
 await panel.getByRole('button',{name:'Revert and close robot editor',exact:true}).click();
 expect((await closed).ok()).toBeTruthy();
 await expect(panel).toHaveCount(0);
});

test('clarifications pause the converter and global settings expose exactly two roles',async({page})=>{
 await open(page);await models(page,true);
 await page.request.post('/api/projects/apple_transfer/plan-definitions',{data:{name:'Clarification plan',goal:'Keep waving'}});
 await page.reload();await page.getByRole('button',{name:'Plans workspace',exact:true}).click();
 let conversions=0;page.on('request',r=>{if(r.url().endsWith('/bind-commands'))conversions++});
 await page.getByRole('button',{name:'Generate plan',exact:true}).click();
 await expect(page.getByLabel('How many times should the robot wave?',{exact:true})).toBeVisible();
 expect(conversions).toBe(0);
 await page.getByRole('button',{name:'Configure AI',exact:true}).click();
 await expect(page.getByLabel('Planner LLM',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Task LLM',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Robot setup AI model',{exact:true})).toHaveCount(0);
 await page.screenshot({path:'artifacts/simple-workflow/global-models.png',animations:'disabled'});
});

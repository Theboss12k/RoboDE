import {test,expect} from '@playwright/test';
async function signIn(page:any){await page.goto('/');await page.getByLabel('Workspace access code').fill('hosted-browser-test-code');await page.getByRole('button',{name:'Open workspace',exact:true}).click();await expect(page.getByLabel('Select project',{exact:true})).toHaveValue('apple_transfer');}
test('reviewed robot setup preserves draft target and never contacts hardware',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));let live=0;page.on('request',r=>{if(r.url().includes('physical-connect'))live++});
 await signIn(page);await page.getByRole('button',{name:'Open configuration',exact:true}).click();
 await page.getByRole('button',{name:'Add robot · guided setup',exact:true}).click();await expect(page.getByRole('heading',{name:'Choose the robot'})).toBeVisible();
 await page.getByRole('button',{name:'Physical · robot hardware',exact:true}).click();
 await expect(page.getByRole('button',{name:'Continue · Controls',exact:true})).toBeDisabled();
 await page.getByLabel('Setup robot model',{exact:true}).selectOption('demo_arm');await page.getByRole('button',{name:'Continue · Controls',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Choose how the robot is controlled'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Create simulator adapter from this robot',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Save & return to library',exact:true}).click();await expect(page.getByRole('heading',{name:'Reviewed robot library'})).toBeVisible();
 await page.getByRole('button',{name:'demo_arm · Controls',exact:true}).click();await expect(page.getByLabel('Existing physical driver')).toHaveCount(0);await expect(page.getByLabel('Reusable control driver')).toBeVisible();
 expect(live).toBe(0);expect(errors).toEqual([]);
});
test('global LLM role selectors and typed task editor are visible',async({page})=>{
 await signIn(page);await page.getByRole('button',{name:'Open configuration',exact:true}).click();await page.getByRole('button',{name:'AI Models',exact:true}).click();
 await expect(page.getByLabel('Planner LLM',{exact:true})).toBeVisible();await expect(page.getByLabel('Task LLM',{exact:true})).toBeVisible();await expect(page.getByLabel('Robot setup AI model',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Save Planner & Task LLM',exact:true}).click();await expect(page.getByText('Role settings saved. Revalidate affected plans.')).toBeVisible();await page.getByRole('button',{name:'Close configuration',exact:true}).click();
 const definition=await(await page.request.post('/api/projects/apple_transfer/plan-definitions',{data:{name:'Typed UI plan',goal:'Raise the shoulder'}})).json();await page.reload();await page.getByRole('button',{name:'Plans workspace',exact:true}).click();
 await expect(page.getByLabel('Plan instruction and actions')).toBeVisible();
 await page.getByRole('button',{name:'Add task',exact:true}).click();await expect(page.getByLabel('Plan name')).toHaveValue('Typed UI plan');
 await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByRole('button',{name:'Saved',exact:true})).toBeVisible();const stored=await(await page.request.get('/api/projects/apple_transfer/plan-definitions/'+definition.id)).json();expect(stored.tasks.at(-1).binding_status).toBe('unresolved');
});
test('virtual wizard tests actual generated code and publishes a complete robot pairing',async({page})=>{
 test.setTimeout(60000);await signIn(page);
 await page.getByRole('button',{name:'Open configuration',exact:true}).click();
 await page.getByRole('button',{name:'Add robot · guided setup',exact:true}).click();
 await page.getByLabel('Setup robot model',{exact:true}).selectOption('demo_arm');
 await page.getByRole('button',{name:'Continue · Controls',exact:true}).click();
 await page.getByRole('button',{name:'Use stationary arm template',exact:true}).click();
 await page.getByRole('button',{name:'Review this driver revision',exact:true}).click();
 await page.getByRole('button',{name:'Test generated driver',exact:true}).click();
 await expect(page.getByRole('region',{name:'Reviewed robot setup',exact:true}).getByRole('status')).toContainText('No hardware was contacted.');
 await page.getByRole('button',{name:'Continue · Mapping',exact:true}).click();
 for(const joint of ['base_yaw','shoulder','elbow','wrist','gripper'])await expect(page.getByLabel(`Function for ${joint}`,{exact:true})).toHaveValue('set_'+joint);
 await page.getByRole('button',{name:'Continue · Test',exact:true}).click();
 for(const joint of ['base_yaw','shoulder','elbow','wrist','gripper']){
  await page.getByLabel('Test mapped actuator',{exact:true}).selectOption(joint);
  await page.getByRole('button',{name:'Test selected actuator',exact:true}).click();
  await expect(page.getByText(/^Tested:/)).toContainText(joint);
 }
 await page.getByLabel('MOVE target',{exact:true}).selectOption('parallel_gripper');
 for(const [axis,value] of [['X','0.3'],['Y','0'],['Z','0.3']])await page.getByLabel(`MOVE ${axis} (m)`,{exact:true}).fill(value);
 await page.getByRole('button',{name:'Compile & test MOVE',exact:true}).click();
 await expect(page.getByRole('region',{name:'Reviewed robot setup',exact:true}).getByRole('status')).toContainText('MOVE');
 await page.getByRole('button',{name:'Continue · Save',exact:true}).click();
 await page.getByLabel('I reviewed the joint mappings, units, tools and motion settings.').check();
 await page.getByRole('button',{name:'Save robot configuration',exact:true}).click();
 await expect(page.getByRole('region',{name:'Reviewed robot setup',exact:true}).getByRole('status')).toContainText('Robot saved.');
 await expect(page.getByText('Actuator tests: passed · MOVE test: passed',{exact:true})).toBeVisible();
});

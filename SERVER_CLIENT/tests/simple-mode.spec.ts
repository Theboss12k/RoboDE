import {test,expect} from '@playwright/test';
// A new user starts in Simple mode: no stored preference.
test.use({storageState:{cookies:[],origins:[]}});
async function signIn(page:any){await page.goto('/');await page.getByLabel('Workspace access code').fill('hosted-browser-test-code');await page.getByRole('button',{name:'Open workspace',exact:true}).click();await expect(page.getByLabel('Select project',{exact:true})).toHaveValue('apple_transfer');}

test('new user sets up the sample robot, tests it and simulates a plan without editing JSON',async({page})=>{
 test.setTimeout(90000);const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await signIn(page);
 await expect(page.getByRole('radio',{name:'Simple',exact:true})).toHaveAttribute('aria-checked','true');
 await page.getByRole('button',{name:'Open configuration',exact:true}).click();
 for(const name of ['Robot library','Control adapters','AI Models','Workspace'])await expect(page.getByRole('button',{name,exact:true})).toBeVisible();
 await expect(page.getByText('Legacy robot definitions & adapters',{exact:true})).toBeHidden();
 await page.getByRole('button',{name:'Add robot · guided setup',exact:true}).click();
 for(const step of ['Robot','Controls','Mapping','Test','Save'])await expect(page.getByLabel('Setup steps',{exact:true}).getByRole('button',{name:new RegExp(`^\\d\\s*${step}$`)})).toBeVisible();
 await page.getByLabel('Setup robot model',{exact:true}).selectOption('demo_arm');
 await page.getByRole('button',{name:'Continue · Controls',exact:true}).click();
 await page.getByRole('button',{name:'Create simulator adapter from this robot',exact:true}).click();
 await expect(page.getByRole('region',{name:'Reviewed robot setup',exact:true}).getByRole('status')).toContainText('joints matched automatically');
 await expect(page.getByText('Import / edit driver manifest',{exact:true})).toBeHidden();
 await expect(page.getByRole('button',{name:'Review this driver revision',exact:true})).toBeHidden();
 await page.getByRole('button',{name:'Review & test adapter',exact:true}).click();
 await expect(page.getByRole('region',{name:'Reviewed robot setup',exact:true}).getByRole('status')).toContainText('No hardware was contacted.');
 await page.getByRole('button',{name:'Continue · Mapping',exact:true}).click();
 for(const joint of ['base_yaw','shoulder','elbow','wrist','gripper'])await expect(page.getByLabel(`Function for ${joint}`,{exact:true})).toHaveValue('set_'+joint);
 // Switching modes keeps unsaved edits and the current step.
 await page.getByLabel('Name for base_yaw',{exact:true}).fill('Turntable');
 await page.getByRole('dialog',{name:'Global configuration'}).getByRole('radio',{name:'Expert',exact:true}).click();
 await expect(page.getByText('Joint roles, scale and coupling',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Name for base_yaw',{exact:true})).toHaveValue('Turntable');
 await page.getByRole('dialog',{name:'Global configuration'}).getByRole('radio',{name:'Simple',exact:true}).click();
 await expect(page.getByText('Joint roles, scale and coupling',{exact:true})).toBeHidden();
 await expect(page.getByLabel('Name for base_yaw',{exact:true})).toHaveValue('Turntable');
 await page.getByRole('button',{name:'Continue · Test',exact:true}).click();
 for(const joint of ['base_yaw','shoulder','elbow','wrist','gripper']){
  await page.getByLabel('Test mapped actuator',{exact:true}).selectOption(joint);
  await page.getByRole('button',{name:'Test selected actuator',exact:true}).click();
  await expect(page.getByText(/^Tested:/)).toContainText(joint);
 }
 await expect(page.getByLabel('MOVE test arguments',{exact:true})).toHaveCount(0);
 await page.getByLabel('MOVE X (m)',{exact:true}).fill('0.3');await page.getByLabel('MOVE Y (m)',{exact:true}).fill('0');await page.getByLabel('MOVE Z (m)',{exact:true}).fill('0.3');
 await page.getByRole('button',{name:'Compile & test MOVE',exact:true}).click();
 await expect(page.getByLabel('Readiness',{exact:true})).toContainText('MOVE tested');
 await page.getByRole('button',{name:'Continue · Save',exact:true}).click();
 await page.getByLabel('I reviewed the joint mappings, units, tools and motion settings.').check();
 await page.getByRole('button',{name:'Save robot configuration',exact:true}).click();
 await expect(page.getByRole('region',{name:'Reviewed robot setup',exact:true}).getByRole('status')).toContainText('Robot saved.');
 await page.getByRole('button',{name:'Control adapters',exact:true}).click();
 await expect(page.getByLabel('Control adapters',{exact:true})).toContainText('Atlas Demo Arm simulator adapter');
 await expect(page.getByLabel('Control adapters',{exact:true})).toContainText('Virtual · simulator');
 await page.getByRole('button',{name:'Close configuration',exact:true}).click();

 const definition=await(await page.request.post('/api/projects/apple_transfer/plan-definitions',{data:{name:'Simple plan',goal:'Move the gripper over the table'}})).json();
 await page.reload();await page.getByRole('button',{name:'Plans workspace',exact:true}).click();
 const actions=page.getByLabel('Plan actions',{exact:true});
 for(const name of ['Generate plan','Validate plan','Run simulation'])await expect(actions.getByRole('button',{name,exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'2 · Bind commands',exact:true})).toBeHidden();
 await page.getByRole('button',{name:'Add task',exact:true}).click();
 await page.getByText('Add a command manually',{exact:true}).click();
 await page.getByLabel('Approved task function',{exact:true}).selectOption('MOVE');
 await expect(page.getByLabel('Function call arguments',{exact:true})).toBeHidden();
 await page.getByLabel('Function X (m)',{exact:true}).fill('0.3');await page.getByLabel('Function Y (m)',{exact:true}).fill('0');await page.getByLabel('Function Z (m)',{exact:true}).fill('0.3');
 await page.getByRole('button',{name:'Add function call',exact:true}).click();
 await actions.getByRole('button',{name:'Validate plan',exact:true}).click();
 await expect(page.getByLabel('Validation progress',{exact:true})).toContainText('Check collisions · done');
 await actions.getByRole('button',{name:'Run simulation',exact:true}).click();
 await expect(page.getByRole('tab',{name:'Simulation'})).toHaveAttribute('aria-selected','true');
 const stored=await(await page.request.get('/api/projects/apple_transfer/plan-definitions/'+definition.id)).json();
 expect(stored.tasks.at(-1).binding_status).toBe('resolved');
 expect(errors).toEqual([]);
});

test('AI Models shows connection types, default status and keeps custom code in Expert mode',async({page})=>{
 await signIn(page);
 await page.getByRole('button',{name:'Open configuration',exact:true}).click();await page.getByRole('button',{name:'AI Models',exact:true}).click();
 await expect(page.getByLabel('Ollama',{exact:true})).toBeVisible();await expect(page.getByLabel('OpenAI-compatible API',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Custom Python function',{exact:true})).toBeHidden();
 await expect(page.getByLabel('Effective AI models',{exact:true})).toContainText('Workspace default');
 await expect(page.getByRole('button',{name:'Test connection & find models',exact:true})).toBeVisible();
 await expect(page.getByLabel('Planner LLM',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Task LLM',{exact:true})).toBeVisible();
 await page.getByRole('dialog',{name:'Global configuration'}).getByRole('radio',{name:'Expert',exact:true}).click();
 await expect(page.getByLabel('Custom Python function',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Planner LLM',{exact:true})).toBeVisible();
});

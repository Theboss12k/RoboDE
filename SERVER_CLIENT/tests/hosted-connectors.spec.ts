import {test,expect} from '@playwright/test';

for(const provider of [
 {kind:'gemini',label:'Google Gemini',url:'https://generativelanguage.googleapis.com/v1beta/openai',env:'GEMINI_API_KEY',model:'fixture-gemini',note:'Independent Gemini adapter',file:'gemini_adapter.py'},
 {kind:'nvidia',label:'NVIDIA API · Nemotron',url:'https://integrate.api.nvidia.com/v1',env:'NVIDIA_API_KEY',model:'nvidia/fixture-nemotron-long-name-30b-a3b',note:'Independent NVIDIA adapter',file:'nvidia_api_adapter.py'},
])test(`${provider.label} is visible in Simple mode and independent of simulator settings`,async({page})=>{
 await page.request.post('/login',{form:{code:'hosted-browser-test-code'}});await page.goto('/');
 await page.getByRole('button',{name:'Open configuration',exact:true}).click();
 await page.getByRole('dialog',{name:'Global configuration'}).getByRole('radio',{name:'Simple',exact:true}).click();
 await page.getByRole('button',{name:'AI Models',exact:true}).click();await page.getByRole('button',{name:'New AI connection',exact:true}).click();
 await page.getByRole('radio',{name:provider.label,exact:true}).check();
 await expect(page.getByLabel('LLM base_url',{exact:true})).toHaveValue(provider.url);
 await expect(page.getByLabel(provider.note,{exact:true})).toBeVisible();
 const discovery:unknown[]=[];
 await page.route('**/api/llm/discover',async route=>{discovery.push(route.request().postDataJSON());await route.fulfill({json:{models:[provider.model]}})});
 await page.route('**/api/llm/adapters/*/status',route=>route.fulfill({json:{available:false,message:`Enter your ${provider.label} API key`,models:[]}}));
 await page.getByLabel('LLM API key',{exact:true}).fill('fixture-key-only');
 await page.getByRole('button',{name:'Check key & find models',exact:true}).click();
 expect(discovery[0]).toMatchObject({connection_type:provider.kind,base_url:provider.url,api_key_env:provider.env});
 await page.getByRole('button',{name:provider.model,exact:true}).click();
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Download adapter function',exact:true}).click();expect((await download).suggestedFilename()).toBe(provider.file);
 await page.getByRole('button',{name:'Save AI model',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'AI model saved.'})).toBeVisible();
 const profiles=await(await page.request.get('/api/llm/adapters')).json();const saved=profiles.adapters.find((a:any)=>a.name===provider.label);
 expect(saved.protocol).toBe('python_function');expect(saved.api_key_env).toBe(provider.env);expect(saved.connection_type).toBe(provider.kind);
 expect(JSON.stringify(profiles)).not.toContain('fixture-key-only');
 const card=page.getByLabel('Configured AI models',{exact:true}).getByRole('button').filter({hasText:provider.label});
 expect(await card.evaluate(el=>el.scrollWidth-el.clientWidth)).toBeLessThanOrEqual(1);
 await page.getByLabel('Planner LLM',{exact:true}).selectOption(saved.id);await page.getByLabel('Task LLM',{exact:true}).selectOption(saved.id);
 await page.getByRole('button',{name:'Save Planner & Task LLM',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Role settings saved.'})).toBeVisible();
 expect(await(await page.request.get('/api/llm/roles')).json()).toMatchObject({planner_adapter_id:saved.id,binding_adapter_id:saved.id});
 await page.screenshot({path:`artifacts/hosted-connectors-20261030/${provider.kind}.png`,animations:'disabled'});
 if(provider.kind==='gemini'){
  // Editing a saved keyed connection must not reuse that key on another host.
  await page.getByRole('radio',{name:'NVIDIA API · Nemotron',exact:true}).check();
  await expect(page.getByLabel('Clear stored key',{exact:true})).toBeChecked();
  await page.getByLabel('LLM model',{exact:true}).fill('nvidia/fixture-nemotron');
  await page.getByRole('button',{name:'Save AI model',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'AI model saved.'})).toBeVisible();
  const changed=(await(await page.request.get('/api/llm/adapters')).json()).adapters.find((a:any)=>a.id===saved.id);
  expect(changed.connection_type).toBe('nvidia');expect(changed.has_api_key).toBe(false);
 }
 await page.request.put('/api/llm/roles',{data:{vision_enabled:false}});await page.request.delete('/api/llm/adapters/'+saved.id);
});

test('switching hosted providers clears draft keys; customizing preserves the connection',async({page})=>{
 await page.request.post('/login',{form:{code:'hosted-browser-test-code'}});await page.goto('/');
 await page.getByRole('button',{name:'Open configuration',exact:true}).click();await page.getByRole('button',{name:'AI Models',exact:true}).click();
 await page.getByRole('button',{name:'New AI connection',exact:true}).click();
 await page.getByRole('radio',{name:'Google Gemini',exact:true}).check();await page.getByLabel('LLM API key',{exact:true}).fill('gemini-draft-key');await page.getByLabel('LLM model',{exact:true}).fill('gemini-fixture');
 await page.getByRole('radio',{name:'NVIDIA API · Nemotron',exact:true}).check();
 await expect(page.getByLabel('LLM API key',{exact:true})).toHaveValue('');await expect(page.getByLabel('LLM model',{exact:true})).toHaveValue('');
 await page.getByLabel('LLM model',{exact:true}).fill('nvidia/fixture-nemotron');
 await page.getByRole('dialog',{name:'Global configuration'}).getByRole('radio',{name:'Expert',exact:true}).click();
 await page.getByRole('button',{name:'Customize adapter function',exact:true}).click();
 await expect(page.getByRole('radio',{name:'Custom Python function',exact:true})).toBeChecked();
 await expect(page.getByLabel('LLM base_url',{exact:true})).toHaveValue('https://integrate.api.nvidia.com/v1');
 await expect(page.getByLabel('LLM model',{exact:true})).toHaveValue('nvidia/fixture-nemotron');
 await expect(page.getByRole('group',{name:'Python LLM adapter editor',exact:true})).toBeVisible();
});

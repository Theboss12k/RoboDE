import {test,expect} from '@playwright/test';
test('normal edition offers an independent Nebius function and lets either role select it',async({page})=>{
 await page.request.post('/login',{form:{code:'hosted-browser-test-code'}});await page.goto('/');
 await page.getByRole('button',{name:'Open configuration',exact:true}).click();
 await page.getByRole('button',{name:'AI Models',exact:true}).click();
 await page.getByRole('button',{name:'New AI connection',exact:true}).click();
 await page.getByRole('radio',{name:'Nebius Token Factory',exact:true}).check();
 await expect(page.getByLabel('LLM base_url',{exact:true})).toHaveValue('https://api.tokenfactory.nebius.com/v1');
 await expect(page.getByLabel('Independent Nebius adapter')).toContainText('any robot or simulator');
 // Hosted discovery is a controlled transport fixture, not a claim of live Nebius access.
 await page.route('**/api/llm/discover',route=>route.fulfill({json:{models:['nvidia/fixture-nemotron']}}));
 await page.getByLabel('LLM API key',{exact:true}).fill('test-only-credential');
 await page.getByRole('button',{name:'Check key & find models',exact:true}).click();
 await page.getByRole('button',{name:'nvidia/fixture-nemotron',exact:true}).click();
 await page.getByRole('button',{name:'Save AI model',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'AI model saved.'})).toBeVisible();
 const all=await(await page.request.get('/api/llm/adapters')).json();
 const profile=all.adapters.find((a:any)=>a.name==='Nebius Token Factory');
 expect(profile.protocol).toBe('python_function');expect(profile.connection_type).toBe('nebius');
 expect(JSON.stringify(all)).not.toContain('test-only-credential');
 await page.getByLabel('Planner LLM',{exact:true}).selectOption(profile.id);
 await page.getByLabel('Task LLM',{exact:true}).selectOption('');
 await page.getByRole('button',{name:'Save Planner & Task LLM',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Role settings saved.'})).toBeVisible();
 const roles=await(await page.request.get('/api/llm/roles')).json();
 expect(roles.planner_adapter_id).toBe(profile.id);expect(roles.binding_adapter_id).toBeNull();
 await page.screenshot({path:'artifacts/nemotron-local-20261030/nebius-connection.png',animations:'disabled'});
 // Leave shared fixtures ready for following tests.
 await page.request.put('/api/llm/roles',{data:{vision_enabled:false}});
 await page.request.delete('/api/llm/adapters/'+profile.id);
});

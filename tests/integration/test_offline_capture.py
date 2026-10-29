import io,json,zipfile,httpx
from services.api.main import create_app

def capture(entries=None):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('capture.json',json.dumps({'format':'robot-room-capture-v1','name':'Offline room'}))
        for name,content in (entries or [('photos/0001.jpg',b'\xff\xd8\xff'+b'photo')]):z.writestr(name,content)
    return buf.getvalue()

async def test_offline_capture_import_is_transactional_and_does_not_change_scene(store):
    app=create_app(store);original=store.load_project('apple_transfer')[3]
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
        r=await c.post('/api/business/projects/apple_transfer/rooms/import-capture',content=capture());assert r.status_code==201,r.text
        data=r.json();assert data['photos']==1 and data['status']=='capture'
        assert store.load_project('apple_transfer')[3]==original
        for bad in [[('../escape.jpg',b'bad')],[('photos/no.jpg',b'not image')],[('photos/a.jpg',b'\xff\xd8\xff'),('photos/a.jpg',b'\xff\xd8\xff')]]:
            r=await c.post('/api/business/projects/apple_transfer/rooms/import-capture',content=capture(bad));assert r.status_code==422,r.text
        assert len((await c.get('/api/business/projects/apple_transfer/rooms')).json())==1

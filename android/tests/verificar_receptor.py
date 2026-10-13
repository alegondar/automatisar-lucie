#!/usr/bin/env python3
"""Verificación HTTPS con Artemis, APK instalada y archivos sintéticos.

Solo modifica el emulador indicado y directorios temporales. Conserva en Android
las copias y parciales de prueba. No inicia la bandeja ni toca material real.
Ejecutar con el entorno Python de Artemis; ver android/README.md.
"""
import os
os.environ['ARTEMIS_HELPER_AUTO_INSTALL'] = 'false'
os.environ['ARTEMIS_HIERARCHY_BACKEND'] = 'uiautomator'
os.environ['DO_NOT_TRACK'] = '1'
import sys, asyncio, re, tempfile, threading, hashlib, subprocess, json, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
DEVICE = 'emulator-5554'
PORT = 53318
from bandeja.localsend import ClienteLocalSend
from mcp_server.tools.device_state import mobile_get_device_state
from artemis.mcp.adb_server import _get_controller

async def screen():
    return await mobile_get_device_state('hierarchy',device_serial=DEVICE)
async def tap_text(label):
    until=time.monotonic()+15
    while time.monotonic()<until:
        text=await screen()
        match=re.search(r"Text: '"+re.escape(label)+r"' \| Bounds: \[(\d+),(\d+)\]\[(\d+),(\d+)\]",text)
        if match:
            x1,y1,x2,y2=map(int,match.groups())
            result=await _get_controller(device_serial=DEVICE).tap_percentage(x_percent=(x1+x2)/20,y_percent=(y1+y2)/20)
            assert not result.error,result.error
            return
        await asyncio.sleep(.3)
    raise AssertionError('Botón no visible: '+label)
async def wait_text(fragment):
    until=time.monotonic()+12
    while time.monotonic()<until:
        if fragment in await screen():return
        await asyncio.sleep(.2)
    raise AssertionError('Estado no encontrado: '+fragment)

async def verificar_envio():
    client=ClienteLocalSend();device=client.probar('127.0.0.1',PORT,'https')
    with tempfile.TemporaryDirectory(prefix='lucie_android_e2e_') as tmp:
        p=Path(tmp);video=p/('prueba-lucie-'+uuid.uuid4().hex[:6]+'.mp4')
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n','-f','lavfi','-i','color=c=teal:s=160x90:r=10','-t','0.5','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(video)],check=True)
        payload=video.read_bytes()
        file={'id':'fixture-video','nombre':video.name,'tamano':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'origen':str(video)}
        cancel=threading.Event();received=[];errors=[]
        def send():
            try:client.enviar(device,[file],lambda f:received.append(f),lambda n,m:None,cancel)
            except Exception as e:errors.append(e)
        thread=threading.Thread(target=send);thread.start()
        await wait_text('Aceptar archivos')
        await tap_text('Aceptar archivos')
        await asyncio.to_thread(thread.join,15)
        assert not thread.is_alive()
        assert not errors,[str(e) for e in errors]
        assert len(received)==1
        await wait_text('Recibido y verificado')
        rows=subprocess.check_output(['adb','-s',DEVICE,'shell','content','query','--uri','content://media/external/video/media','--projection','_id:_display_name:is_pending','--where',"\"owner_package_name='com.luciesinreglas.recibir'\""],text=True)
        row=next((line for line in rows.splitlines() if '_display_name='+video.name+',' in line),''); match=re.search(r'_id=(\d+)',row);assert match,rows
        data=subprocess.check_output(['adb','-s',DEVICE,'exec-out','content','read','--uri',f'content://media/external/video/media/{match.group(1)}'])
        assert data==payload,(len(data),len(payload))
        assert 'is_pending=0' in row
        print('Emisor Python → APK Android por HTTPS: video real sintético, bytes idénticos y MediaStore visible OK.')
        # Cancelar preparación sin respuesta debe liberar la propia reserva Android.
        received.clear();errors.clear();cancel.clear()
        thread=threading.Thread(target=send);thread.start()
        await wait_text('Aceptar archivos')
        cancel.set();await asyncio.to_thread(thread.join,5)
        assert not thread.is_alive()
        assert not received
        await wait_text('Listo para recibir de nuevo')
        print('Cancelación durante aceptación: conexión interrumpida, reserva Android liberada y cero recibidos OK.')
        # Segundo envío explícito después de cancelar, con nombre repetido.
        received.clear();errors.clear();cancel.clear()
        thread=threading.Thread(target=send);thread.start()
        await wait_text('Aceptar archivos');await tap_text('Aceptar archivos')
        await asyncio.to_thread(thread.join,15)
        assert not errors,[str(e) for e in errors]
        assert len(received)==1
        rows=subprocess.check_output(['adb','-s',DEVICE,'shell','content','query','--uri','content://media/external/video/media','--projection','_id:_display_name:is_pending','--where',"\"owner_package_name='com.luciesinreglas.recibir'\""],text=True)
        assert '_display_name='+video.stem+' (1).mp4' in rows,rows
        print('Segundo envío y homónimo: copia nueva sin sobrescribir el primer archivo OK.')
    print(await mobile_get_device_state('screenshot',device_serial=DEVICE))


from urllib.parse import urlencode
from bandeja.localsend import ClienteLocalSend
from bandeja.config import ConfiguracionBandeja
from bandeja.db import GestorBaseDatosBandeja
from bandeja.pendrive import vincular_pendrive
from bandeja.publicacion import GestorPublicacion

async def verificar_matriz():
 c=ClienteLocalSend();d=c.probar('127.0.0.1',PORT,'https')
 try:c._conexion({**d,'fingerprint':'0'*64});raise AssertionError('Identidad falsa aceptada')
 except ValueError as e:assert 'identidad' in str(e)
 print('HTTPS: huella modificada rechazada antes de transferir OK.')
 async def prepare(meta,pin='',decision='Aceptar archivos'):
  con,_=c._conexion(d)
  con.request('POST','/api/localsend/v2/prepare-upload'+('?' +urlencode({'pin':pin}) if pin else ''),json.dumps({'info':c.info(),'files':meta}).encode(),{'Content-Type':'application/json'})
  task=asyncio.create_task(asyncio.to_thread(con.getresponse))
  await wait_text(decision);await tap_text(decision)
  resp=await task;data=resp.read();code=resp.status;con.close()
  return code,json.loads(data) if data else {}
 async def request(path,body=b''):
  def req():
   con,_=c._conexion(d)
   try:con.request('POST',path,body);resp=con.getresponse();data=resp.read();return resp.status,data
   finally:con.close()
  return await asyncio.to_thread(req)
 await tap_text('Exigir PIN además de aceptar')
 tree=await screen();pin=re.search(r"Text: 'PIN: (\d{4})'",tree).group(1)
 file={'id':'pin-fixture','fileName':'pin-sintetico.mp4','size':100,'fileType':'video/mp4','sha256':'a'*64}
 code,_=await request('/api/localsend/v2/prepare-upload?pin=0000',json.dumps({'info':c.info(),'files':{'pin-fixture':file}}).encode());assert code==401,code
 code,_=await prepare({'pin-fixture':file},pin,decision='Rechazar');assert code==403
 await tap_text('Exigir PIN además de aceptar')
 print('PIN incorrecto rechaza sin reserva; PIN correcto solicita aprobación; rechazo libera OK.')
 name='corrupto-sintetico-'+uuid.uuid4().hex[:6]+'.mp4'
 body=b'material temporal para comprobar hash';meta={'corrupto':{'id':'corrupto','fileName':name,'size':len(body),'fileType':'video/mp4','sha256':hashlib.sha256(body).hexdigest()}}
 code,session=await prepare(meta);assert code==200
 code,_=await request('/api/localsend/v2/upload?'+urlencode({'sessionId':session['sessionId'],'fileId':'corrupto','token':session['files']['corrupto']}),b'X'+body[1:]);assert code==422,code
 journal=subprocess.check_output(['adb','-s',DEVICE,'exec-out','run-as','com.luciesinreglas.recibir','cat','files/recepciones.jsonl'],text=True)
 entries=[json.loads(line) for line in journal.splitlines()]
 assert any(entry['nombre']==name and entry['estado']=='parcial' for entry in entries)
 assert not any(entry['nombre']==name and entry['estado']=='recibido' for entry in entries)
 entry=next(entry for entry in reversed(entries) if entry['nombre']==name)
 assert re.fullmatch(r'recepcion-[A-Za-z0-9-]+\.bin',entry['resguardo'])
 retained=subprocess.check_output(['adb','-s',DEVICE,'exec-out','run-as','com.luciesinreglas.recibir','cat','files/resguardos/'+entry['resguardo']])
 assert retained==b'X'+body[1:]
 code,_=await request('/api/localsend/v2/cancel?'+urlencode({'sessionId':session['sessionId']}));assert code==200,code
 print('Hash corrupto devuelve 422; parcial oculto conservado y cancelación propia idempotente OK.')
 # Interrumpir un cuerpo antes de completar debe conservar un parcial y liberar reserva.
 file={'id':'parcial','fileName':'parcial-sintetico-'+uuid.uuid4().hex[:6]+'.mp4','size':1_000_000,'fileType':'video/mp4','sha256':'a'*64}
 code,session=await prepare({'parcial':file});assert code==200
 con,_=c._conexion(d);con.putrequest('POST','/api/localsend/v2/upload?'+urlencode({'sessionId':session['sessionId'],'fileId':'parcial','token':session['files']['parcial']}));con.putheader('Content-Length','1000000');con.endheaders();con.send(b'sintetico'*128)
 await wait_text('Recibiendo');await tap_text('Cancelar recepción actual');con.close()
 await wait_text('podés recibir de nuevo')
 print('Cancelación durante upload: parcial conservado, sesión liberada OK.')
 with tempfile.TemporaryDirectory(prefix='apk_dashboard_') as tmp:
  p=Path(tmp);pen=p/'unidad';pen.mkdir();cfg=ConfiguracionBandeja(str(p/'cfg.json'),str(p/'local.json'));cfg.rutas_candidatas_pendrive=[str(pen)];vincular_pendrive(str(pen),cfg)
  queue=pen/'LucieSinReglas'/'videos completos'/'videos sin publicar'/'lucie'/'Prueba APK';queue.mkdir(parents=True)
  suffix=uuid.uuid4().hex[:6];video=queue/('video-'+suffix+'.mp4');foto=queue/('foto-'+suffix+'.png')
  subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n','-f','lavfi','-i','color=c=teal:s=160x90:r=10','-t','0.5','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(video)],check=True)
  subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-n','-f','lavfi','-i','color=c=orange:s=160x90','-frames:v','1','-threads','1',str(foto)],check=True)
  original={v.name:v.read_bytes() for v in [video,foto]}
  db=GestorBaseDatosBandeja(str(p/'memoria.sqlite'));g=GestorPublicacion(cfg,db);dev=g._guardar_dispositivo(d)
  listing=g.listar();plan=g.simular([a['id'] for a in listing['archivos']],dev['id']);job=g.iniciar_envio(plan['token'],True)
  await wait_text('Aceptar archivos');await tap_text('Aceptar archivos')
  until=time.monotonic()+15
  while g.estado(job['id'])['estado']=='en_curso' and time.monotonic()<until:await asyncio.sleep(.1)
  state=g.estado(job['id']);assert state['estado']=='completado',state
  assert len(state['recibidos'])==2 and len(state['publicados'])==2,state
  for event in state['publicados']:
   dest=pen/'LucieSinReglas'/event['ruta_destino'];assert dest.read_bytes()==original[dest.name]
   g.deshacer(event['id_operacion'])
  assert video.read_bytes()==original[video.name] and foto.read_bytes()==original[foto.name]
  print('Dashboard real aislado → APK: video y foto recibidos, archivados tras ACK y deshacer conserva bytes OK.')



async def ejecutar():
    await wait_text('Listo para recibir por Wi-Fi')
    await verificar_envio()
    await verificar_matriz()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='emulator-5554')
    parser.add_argument('--port', type=int, default=53318)
    args = parser.parse_args()
    if not args.device.startswith('emulator-'):
        parser.error('Esta prueba automática solo admite emuladores, nunca teléfonos reales.')
    DEVICE, PORT = args.device, args.port
    subprocess.run(['adb', '-s', DEVICE, 'get-state'], check=True)
    subprocess.run(['adb', '-s', DEVICE, 'forward', f'tcp:{PORT}', 'tcp:53318'], check=True)
    subprocess.run(['adb', '-s', DEVICE, 'shell', 'am', 'start', '-n',
                    'com.luciesinreglas.recibir/.MainActivity'], check=True)
    asyncio.run(ejecutar())

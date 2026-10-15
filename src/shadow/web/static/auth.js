/* Browser-native WebAuthn. Authentication state stays in HttpOnly cookies. */
function safeReturn(value, origin) {
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))return '/today';
  try {const url=new URL(value,origin);return url.origin===origin&&url.pathname!=='/login'?url.pathname+url.search:'/today'}catch(_){return '/today'}
}
function decodeOptions(input) {
  const options=structuredClone(input);
  const bytes=text=>Uint8Array.from(atob(text.replaceAll('-','+').replaceAll('_','/')),char=>char.charCodeAt(0)).buffer;
  options.challenge=bytes(options.challenge);
  if(options.user)options.user.id=bytes(options.user.id);
  for(const field of ['allowCredentials','excludeCredentials'])for(const item of options[field]||[])item.id=bytes(item.id);
  return options;
}
function serializeCredential(credential) {
  if(credential.toJSON)return credential.toJSON();
  const encode=buffer=>btoa(Array.from(new Uint8Array(buffer),byte=>String.fromCharCode(byte)).join('')).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
  const response={};for(const field of ['clientDataJSON','attestationObject','authenticatorData','signature','userHandle'])if(field in credential.response)response[field]=credential.response[field]?encode(credential.response[field]):null;
  if(credential.response.getTransports)response.transports=credential.response.getTransports();
  return {id:credential.id,rawId:encode(credential.rawId),type:credential.type,response,clientExtensionResults:credential.getClientExtensionResults?.()||{},authenticatorAttachment:credential.authenticatorAttachment||null};
}
if(typeof module!=='undefined')module.exports={safeReturn,decodeOptions,serializeCredential};
if(typeof window!=='undefined')(()=>{
 const originalFetch=window.fetch.bind(window);
 async function api(path,body,method='POST'){
   const response=await originalFetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
   const data=await response.json().catch(()=>({}));const messages={'Password not accepted.':'密码不正确，请重试。','Please sign in.':'请先登录。','Please sign in again to confirm this action.':'请先重新登录，再确认这个操作。','Code expired or not accepted.':'设备码已过期、已使用或不正确，请重新生成。','Passkey verification failed. Try again.':'通行密钥验证失败，请重试或使用备用密码。','Too many attempts. Try again later.':'尝试次数过多，请稍后再试。','Ceremony expired. Try again.':'验证已过期，请重新开始。','Authentication is not configured.':'尚未启用应用登录，请先在运行 Shadow 的电脑上完成初始化。'};if(!response.ok)throw Error(messages[data.detail]||data.detail||'未能完成验证，请重试。');return data;
 }
 const supportsPasskey=()=>Boolean(window.isSecureContext&&window.PublicKeyCredential&&navigator.credentials);
 async function passkey(mode,name,remember=true){
   const {cid,options}=await api('/api/auth/passkey/options',{mode,name});
   const publicKey=decodeOptions(options);
   const credential=mode==='register'?await navigator.credentials.create({publicKey}):await navigator.credentials.get({publicKey});
   if(!credential)throw Error('验证已取消');
   return api('/api/auth/passkey/verify',{cid,credential:serializeCredential(credential),name,remember});
 }
 function message(node,error){if(node)node.textContent=error.name==='NotAllowedError'||error.name==='AbortError'?'验证已取消，可以再试一次或使用备用密码。':error.message;}
 function wireLogin(form,onSuccess){
   const note=form.querySelector('[data-auth-note]'),remember=()=>form.querySelector('[name=remember]')?.checked!==false;
   const run=async(action)=>{const buttons=[...form.querySelectorAll('button')],disabled=new Map(buttons.map(button=>[button,button.disabled]));buttons.forEach(button=>button.disabled=true);if(note)note.textContent='正在验证…';try{await action();await onSuccess()}catch(error){message(note,error)}finally{buttons.forEach(button=>button.disabled=disabled.get(button))}};
   form.addEventListener('submit',event=>{event.preventDefault();run(()=>api('/api/auth/password',{password:form.querySelector('[name=password]').value,remember:remember()}))});
   const key=form.querySelector('[data-passkey-login]');if(key){key.disabled=!supportsPasskey();key.addEventListener('click',()=>run(()=>passkey('login',undefined,remember())))}
   const redeem=form.querySelector('[data-device-redeem]');redeem?.addEventListener('click',()=>run(()=>api('/api/auth/device-redeem',{code:form.querySelector('[name=device]').value,remember:remember()})));
 }
 let loginDialog=null,loginTimer=null;
 function requestLogin(){
   if(location.pathname==='/login'||loginDialog?.open)return;if(window.ShadowSession?.isRecording()){if(!loginTimer)loginTimer=setTimeout(()=>{loginTimer=null;requestLogin()},1000);return;}if(typeof stopLoops==='function')stopLoops();
   const dialog=document.createElement('dialog');dialog.id='auth-expired';dialog.className='settings-dialog';dialog.setAttribute('aria-labelledby','auth-expired-title');
   const body=document.createElement('div');body.className='sheet-body';
   const title=document.createElement('h2');title.id='auth-expired-title';title.textContent='请重新登录';
   const description=document.createElement('p');description.textContent='登录已过期。当前页面和录音会保留，验证后可继续提交。';
   const form=document.createElement('form');form.className='auth-form';
   const key=document.createElement('button');key.type='button';key.className='primary';key.dataset.passkeyLogin='';key.textContent='使用面容／指纹登录';
   const password=document.createElement('input');password.type='password';password.name='password';password.autocomplete='current-password';password.inputMode='numeric';password.placeholder='6 位数字备用密码';password.setAttribute('aria-label','备用密码');
   const submit=document.createElement('button');submit.type='submit';submit.textContent='使用密码登录';
   const note=document.createElement('p');note.dataset.authNote='';note.className='hint';note.setAttribute('role','status');form.append(key,password,submit,note);body.append(title,description,form);dialog.append(body);document.body.append(dialog);loginDialog=dialog;
   wireLogin(form,async()=>{password.value='';window.ShadowSheets?.close(dialog);if(dialog.open)dialog.close();window.ShadowUI?.toast('已登录，可以继续提交。');document.dispatchEvent(new Event('shadow:authenticated'))});
   dialog.addEventListener('close',()=>{loginDialog=null;dialog.remove()},{once:true});if(window.ShadowSheets)window.ShadowSheets.open(dialog);else dialog.showModal();
 }
 window.fetch=async(input,options)=>{const response=await originalFetch(input,options);let url;try{url=new URL(typeof input==='string'?input:input.url||String(input),location.href)}catch(_){}if(response.status===401&&url?.origin===location.origin&&!url.pathname.startsWith('/api/auth/'))requestLogin();return response;};
 window.ShadowAuth={requestLogin};
 document.addEventListener('DOMContentLoaded',async()=>{
  const form=document.getElementById('login-form');
  if(form){const next=safeReturn(form.dataset.next,location.origin);wireLogin(form,async()=>location.replace(next));const code=new URLSearchParams(location.hash.slice(1)).get('device');if(code){form.querySelector('[name=device]').value=code;form.querySelector('details').open=true;history.replaceState(null,'',location.pathname+location.search)}}
  const account=document.getElementById('account-panel');if(!account)return;
  const note=document.getElementById('account-note');
  async function refresh(){try{const state=await api('/api/auth/status',null,'GET');document.getElementById('auth-disabled').hidden=state.enabled;document.getElementById('auth-account').hidden=!state.enabled;const list=document.getElementById('passkey-list');list.replaceChildren();for(const credential of state.passkeys||[]){const row=document.createElement('li');row.className='grouped-row';const label=document.createElement('span');label.textContent=credential.name||'通行密钥';const remove=document.createElement('button');remove.type='button';remove.textContent='移除';remove.className='danger';remove.addEventListener('click',()=>run(remove,async()=>{if(!await window.ShadowUI.confirm({title:'移除这个通行密钥？',message:'已登录设备会保持登录；以后仍可使用备用密码或其他通行密钥。',confirm:'移除',danger:true}))return;await api('/api/auth/passkey/'+encodeURIComponent(credential.id),null,'DELETE');await refresh()}));row.append(label,remove);list.append(row)}if(!list.children.length){const row=document.createElement('li');row.className='grouped-row';row.textContent='还没有绑定通行密钥';list.append(row)}}catch(error){message(note,error)}}
  const run=async(button,action)=>{button.disabled=true;note.textContent='';try{await action()}catch(error){message(note,error)}finally{button.disabled=false}};
  const add=document.getElementById('add-passkey');add.disabled=!supportsPasskey();add.addEventListener('click',()=>run(add,async()=>{await passkey('register',document.getElementById('passkey-name').value||'我的设备');await refresh();note.textContent='通行密钥已添加。'}));
  const device=document.getElementById('create-device-code');device.addEventListener('click',()=>run(device,async()=>{const data=await api('/api/auth/device-code',{});const sheet=document.getElementById('device-code-sheet');document.getElementById('device-code').textContent=data.code;document.getElementById('device-qr').src=`data:image/svg+xml;base64,${btoa(data.qr_svg)}`;document.getElementById('device-code-note').textContent='10 分钟内有效，仅可使用一次。';window.ShadowSheets.open(sheet);const expiry=Date.now()+data.expires_in*1000;const timer=setInterval(()=>{if(Date.now()>=expiry){document.getElementById('device-code').textContent='已过期';document.getElementById('device-qr').removeAttribute('src');document.getElementById('device-code-note').textContent='请关闭后重新生成设备码。';clearInterval(timer)}},1000);sheet.addEventListener('close',()=>{clearInterval(timer);document.getElementById('device-code').textContent='';document.getElementById('device-qr').removeAttribute('src')},{once:true})}));
  for(const [id,all]of [['logout-current',false],['logout-all',true]]){const button=document.getElementById(id);button.addEventListener('click',()=>run(button,async()=>{if(all&&!await window.ShadowUI.confirm({title:'退出所有设备？',message:'所有已登录设备都需要重新验证，练习记录会保留。',confirm:'退出所有设备',danger:true}))return;await api('/api/auth/logout',{all});location.assign('/login')}));}
  refresh();
 });
})();

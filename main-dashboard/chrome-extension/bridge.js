// Dedicated bridge also understands old replica pages, but never runs on8766.
if(/^http:\/\/(127\.0\.0\.1|localhost):8765$/.test(location.origin)){
  const key="__codemaoMainBridgeInstalled",version="1.6.79";
  const previous=globalThis[key];
  if(!previous||previous.version!==version||previous.extensionId!==chrome.runtime.id){
    if(previous?.listener)window.removeEventListener("message",previous.listener);
    const listener=event=>{
      const input=event.data;
      if(event.source!==window||!input?.id||input.source!=="codemao-dashboard")return;
      if(input.connectorId&&input.connectorId!==chrome.runtime.id)return;
      const message={...input,source:"codemao-dashboard",localBase:location.origin};
      const replySource=input.source==="codemao-dashboard"?"codemao-crm-extension":"codemao-crm-extension";
      const relay=(attempt=0)=>{
        try{chrome.runtime.sendMessage(message,response=>{
          const runtimeError=chrome.runtime.lastError?.message;
          if(runtimeError&&attempt<2){setTimeout(()=>relay(attempt+1),600*(attempt+1));return;}
          window.postMessage({source:replySource,id:message.id,...(response||{ok:false,error:runtimeError||"主看板连接器服务暂时不可用，请刷新页面后重试"})},"*");
        });}catch{window.postMessage({source:replySource,id:message.id,ok:false,error:"主看板连接器已重新加载，请按Ctrl+F5刷新此页"},"*");}
      };
      relay();
    };
    globalThis[key]={version,extensionId:chrome.runtime.id,listener};
    window.addEventListener("message",listener);
    window.postMessage({source:"codemao-crm-extension",type:"ready"},"*");
  }
}

'use strict';
window.DraftEditor=(()=>{
  const svg=$('editor-canvas'),G=SelectionGeometry,NS='http://www.w3.org/2000/svg',METERS_PER_UNIT=.5;
  // shortcut: this draft uses a schematic plane; production editing must retain the existing map projection.
  const initial=shapeToLocalLoop(makeDefaultShape('stadium',{lat:0,lng:0}),15).map(p=>({x:500-p.y/METERS_PER_UNIT,y:345+p.x/METERS_PER_UNIT}));
  const tracks=new Map([['campus',{id:'campus_default',name:'默认操场轨迹',description:'校园操场环线示例',points:initial,undo:[],redo:[],dirty:false}]]);
  const shapeNames={stadium:'操场',rect:'矩形',circle:'圆形'};
  let currentKey='campus',tool='pan',selected=[],frame=null,pending=null,drag=null,nextTrack=1,view={x:0,y:0,width:1000,height:700};
  const clone=points=>points.map(p=>({...p}));
  const track=()=>tracks.get(currentKey);
  const points=()=>track().points;
  const editable=()=>pending?pending.points:selected.map(i=>points()[i]);
  const node=(tag,attrs={},className)=>{const element=document.createElementNS(NS,tag);for(const [name,value]of Object.entries(attrs))element.setAttribute(name,value);if(className)element.setAttribute('class',className);return element;};
  const pathData=pts=>pts.length?'M'+pts.map(p=>`${p.x},${p.y}`).join('L')+(pts.length>2?'Z':''):'';
  function summary(item){const pts=item.points;let distance=0,area=0;for(let i=0;i<pts.length;i++){const a=pts[i],b=pts[(i+1)%pts.length];distance+=Math.hypot(b.x-a.x,b.y-a.y)*METERS_PER_UNIT;area+=a.x*b.y-b.x*a.y;}return {...item,points:clone(pts),distance,direction:pts.length<3?'尚未成环':area>=0?'顺时针':'逆时针'};}
  function syncLibrary(){
    $('track-library').replaceChildren();const chosen=$('track-choice').value;$('track-choice').replaceChildren();
    for(const [key,item]of tracks){
      const button=document.createElement('button');button.className='track-row';button.type='button';button.setAttribute('aria-pressed',String(key===currentKey));button.dataset.trackKey=key;
      const icon=node('svg',{},'icon');icon.setAttribute('aria-hidden','true');icon.append(node('use',{href:'#i-map'}));button.append(icon);const label=document.createElement('span'),name=document.createElement('strong'),detail=document.createElement('small');name.textContent=item.name||'未命名轨迹';detail.textContent=`${item.points.length} 节点${item.dirty?' · 已修改':''}`;label.append(name,detail);button.append(label);button.addEventListener('click',()=>loadTrack(key));$('track-library').append(button);
      const option=document.createElement('option');option.value=key;option.textContent=item.name||'未命名轨迹';$('track-choice').append(option);
    }
    $('track-choice').value=tracks.has(chosen)?chosen:currentKey;
  }
  function changed(){track().dirty=true;if($('track-choice').value===currentKey)markStale();syncLibrary();renderRoutePreview();}
  function remember(before){track().undo.push(clone(before));if(track().undo.length>80)track().undo.shift();track().redo=[];changed();}
  function setPoints(next){const before=clone(points());track().points=next;remember(before);render();}
  function clearSelection(){selected=[];frame=null;render();}
  function setTool(next){if(drag)finish(true);if(pending)cancelShape(false);tool=next;selected=[];frame=null;document.querySelectorAll('button[data-tool]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.tool===tool)));svg.dataset.tool=tool;render();}
  function applyView(){svg.setAttribute('viewBox',`${view.x} ${view.y} ${view.width} ${view.height}`);}
  function fit(){const all=[...points(),...(pending?pending.points:[])];const bounds=G.bounds(all);if(!bounds){view={x:0,y:0,width:1000,height:700};}else{const width=Math.max(240,bounds.width*1.6),height=Math.max(200,bounds.height*1.5);view={x:bounds.x-width/2,y:bounds.y-height/2,width,height};}applyView();}
  function zoom(factor,anchor){if(drag)finish(true);const next=view.width*factor;if(next<100||next>8000)return;const center=anchor||{x:view.x+view.width/2,y:view.y+view.height/2};view={x:center.x-(center.x-view.x)*factor,y:center.y-(center.y-view.y)*factor,width:next,height:view.height*factor};applyView();}
  function getPosition(event,matrix=svg.getScreenCTM().inverse()){return new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix);}
  function frameConflict(){if(!pending||points().length<3)return false;return points().some((a,i)=>pending.points.some((b,j)=>segmentsMeet(a,points()[(i+1)%points().length],b,pending.points[(j+1)%pending.points.length])));}
  function render(){
    const route=points(),paths=$('editor-paths'),nodes=$('editor-nodes'),overlay=$('editor-selection');paths.replaceChildren();nodes.replaceChildren();overlay.replaceChildren();
    paths.append(node('path',{d:pathData(route),opacity:pending ? 0.45 : 1},'route-line'));
    if(pending)paths.append(node('path',{d:pathData(pending.points)},'ghost-line'));
    const radius=Math.max(2.5,view.width/240);
    route.forEach((p,index)=>{
      if(!pending){nodes.append(node('circle',{cx:p.x,cy:p.y,r:radius*3,'data-node':index},'node-hit'));nodes.append(node('circle',{cx:p.x,cy:p.y,r:radius,'pointer-events':'none'},'route-node'+(selected.includes(index)?' selected':'')));}
      if(!pending&&tool!=='select'&&tool!=='erase'&&route.length>1){const next=route[(index+1)%route.length];nodes.append(node('circle',{cx:(p.x+next.x)/2,cy:(p.y+next.y)/2,r:radius*.8,'data-mid':index},'midpoint'));}
    });
    if(pending)for(const p of pending.points)nodes.append(node('circle',{cx:p.x,cy:p.y,r:radius*.8,'pointer-events':'none'},'route-node'));
    if(drag?.key==='marquee'){const a=drag.start,b=drag.last;overlay.append(node('rect',{x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(a.x-b.x),height:Math.abs(a.y-b.y)},'marquee'));}
    else if(frame&&(pending||selected.length)){
      const group=node('g',{transform:`translate(${frame.x} ${frame.y}) rotate(${frame.angle*180/Math.PI})`}),w=Math.max(frame.width,radius*8),h=Math.max(frame.height,radius*8);
      group.append(node('rect',{x:-w/2,y:-h/2,width:w,height:h,'data-handle':'move'},'selection-box'));
      for(const [key,[x,y]]of Object.entries(G.handles)){const disabled=x&&frame.width<1e-6||y&&frame.height<1e-6;const handle=node('rect',{x:x*w/2-radius,y:y*h/2-radius,width:radius*2,height:radius*2,'data-handle':key,'data-disabled':Boolean(disabled)},'selection-handle');handle.style.cursor=disabled?'not-allowed':key+'-resize';group.append(handle);}
      const ry=-h/2-radius*7;group.append(node('line',{x1:0,y1:-h/2,x2:0,y2:ry},'rotation-line'));const rotation=node('circle',{cx:0,cy:ry,r:radius*1.4,'data-handle':'rotate'},'selection-handle');rotation.style.cursor='grab';group.append(rotation);overlay.append(group);
    }
    const stats=summary(track());$('editor-point-count').textContent=`${route.length} 节点`;$('editor-loop-distance').textContent=`${stats.distance.toFixed(1)} m`;$('editor-selected-count').textContent=pending?`正在放置 ${shapeNames[pending.type]}`:selected.length?`已选 ${selected.length} 个节点`:'未选择节点';
    $('editor-undo').disabled=!track().undo.length;$('editor-redo').disabled=!track().redo.length;$('save-track').disabled=route.length<3||Boolean(pending);$('use-track').disabled=route.length<3||Boolean(pending);$('editor-dirty').textContent=track().dirty?'已修改 · 保留在当前页面':'页面草稿';
    const hasSelection=Boolean(frame&&(pending||selected.length));$('selection-empty').hidden=hasSelection;$('selection-properties').hidden=!hasSelection;$('selection-title').textContent=pending?`放置${shapeNames[pending.type]}`:'节点选区';$('selected-actions').hidden=Boolean(pending);$('pending-actions').hidden=!pending;$('select-all').disabled=!route.length||Boolean(pending);
    if(hasSelection){for(const [id,value]of Object.entries({'selection-width':(frame.width*METERS_PER_UNIT).toFixed(1),'selection-height':(frame.height*METERS_PER_UNIT).toFixed(1),'selection-angle':Math.round(frame.angle*180/Math.PI)}))if(document.activeElement!==$(id))$(id).value=value;$('selection-width').disabled=frame.width<1e-6;$('selection-height').disabled=frame.height<1e-6;}
    if(pending){const conflict=frameConflict();$('add-shape').disabled=conflict;$('pending-warning').textContent=conflict?'图形与现有路线重叠，拖到空白处后再添加。也可以新建空白轨迹':'确认后接入当前环线，保留已有节点；添加操作可撤销';}
    document.querySelectorAll('[data-shape]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.shape===pending?.type)));
    $('canvas-tip').textContent=pending?'拖动图形及手柄调整，确认后添加；Esc 取消':tool==='select'?'拖出矩形框选；选框内移动，顶部柄旋转；Esc 取消':tool==='draw'?'点击空白处添加节点；点击线段中点插入节点':tool==='erase'?'点击节点删除；删除后可按 Ctrl+Z 撤销':'拖动地图或节点；点击线段中点插入节点；滚轮缩放';
  }
  function begin(event){
    if(event.button!==0&&event.button!==1)return;if(drag)return;svg.focus({preventScroll:true});event.preventDefault();
    const start=getPosition(event),target=event.target.closest('[data-handle],[data-node],[data-mid]');
    let key=event.button===1?'pan':target?.dataset.handle;
    if(target?.dataset.disabled==='true')return;
    if(!key&&pending)return;
    if(!key&&target?.hasAttribute('data-mid')&&tool!=='erase'&&tool!=='select'){
      const index=Number(target.dataset.mid),next=clone(points()),b=next[(index+1)%next.length];next.splice(index+1,0,{x:(next[index].x+b.x)/2,y:(next[index].y+b.y)/2});setPoints(next);return;
    }
    if(!key&&target?.hasAttribute('data-node')){
      const index=Number(target.dataset.node);
      if(tool==='erase'){selected=[];frame=null;setPoints(points().filter((_,i)=>i!==index));return;}
      if(tool==='select'){selected=event.shiftKey?(selected.includes(index)?selected.filter(i=>i!==index):[...selected,index]):[index];frame=G.bounds(editable());render();return;}
      key='node';selected=[];frame=null;
    }
    if(!key)key=tool==='select'?'marquee':tool==='draw'?'draw':tool==='erase'?null:'pan';if(!key)return;
    drag={id:event.pointerId,key,start,last:start,matrix:svg.getScreenCTM().inverse(),snapshot:clone(points()),selected:[...selected],frame:frame?{...frame}:null,view:{...view},pendingPoints:pending?clone(pending.points):null,node:target?.dataset.node===undefined?null:Number(target.dataset.node),changed:false};
    if(key==='marquee'){selected=[];frame=null;}svg.setPointerCapture(event.pointerId);render();
  }
  function update(event){
    if(!drag||drag.id!==event.pointerId)return;const end=getPosition(event,drag.matrix);drag.last=end;const dx=end.x-drag.start.x,dy=end.y-drag.start.y;
    if(drag.key==='pan'){view={...drag.view,x:drag.view.x-dx,y:drag.view.y-dy};applyView();return;}
    if(drag.key==='draw')return;
    if(drag.key==='marquee'){selected=points().flatMap((p,i)=>G.inside(drag.start,end,p)?[i]:[]);frame=G.bounds(editable());}
    else if(drag.key==='node'){track().points=drag.snapshot.map((p,i)=>i===drag.node?{x:p.x+dx,y:p.y+dy}:{...p});drag.changed=Math.hypot(dx,dy)>.01;}
    else{
      const nextFrame=G.transform(drag.frame,drag.key,drag.start,end);if(!Number.isFinite(nextFrame.x)||!Number.isFinite(nextFrame.y)||nextFrame.width>10000||nextFrame.height>10000)return;
      if(pending)pending.points=drag.pendingPoints.map(p=>G.point(p,drag.frame,nextFrame));else track().points=drag.snapshot.map((p,i)=>drag.selected.includes(i)?G.point(p,drag.frame,nextFrame):{...p});frame=nextFrame;drag.changed=Math.hypot(dx,dy)>.01;
    }
    render();
  }
  function finish(cancel=false){
    if(!drag)return;const previous=drag;drag=null;
    if(cancel){track().points=previous.snapshot;if(pending&&previous.pendingPoints)pending.points=previous.pendingPoints;selected=previous.selected;frame=previous.frame;view=previous.view;applyView();}
    else if(previous.key==='draw'){const distance=Math.hypot(previous.last.x-previous.start.x,previous.last.y-previous.start.y);if(distance<8){track().points.push({x:previous.start.x,y:previous.start.y});remember(previous.snapshot);}}
    else if(previous.changed&&!pending){remember(previous.snapshot);}
    if(svg.hasPointerCapture(previous.id))svg.releasePointerCapture(previous.id);render();
  }
  function selectAll(){if(pending)cancelShape(false);tool='select';svg.dataset.tool=tool;document.querySelectorAll('button[data-tool]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.tool===tool)));selected=points().map((_,i)=>i);frame=G.bounds(editable());render();}
  function removeSelected(){if(!selected.length)return;const keep=points().filter((_,i)=>!selected.includes(i));selected=[];frame=null;setPoints(keep);notify('已删除所选节点，可以撤销');}
  function undo(redo=false){if(drag)finish(true);if(pending){cancelShape();return;}const from=redo?track().redo:track().undo,to=redo?track().undo:track().redo;if(!from.length)return;to.push(clone(points()));track().points=from.pop();selected=[];frame=null;changed();render();}
  function changeFrame(next){if(!frame)return;const before=clone(points()),from={...frame};if(pending)pending.points=pending.points.map(p=>G.point(p,from,next));else track().points=points().map((p,i)=>selected.includes(i)?G.point(p,from,next):p);frame=next;if(!pending)remember(before);render();}
  function resizeSelection(id){if(!frame||!$(id).checkValidity()){$(id).reportValidity();return;}const next={...frame};if(id==='selection-angle')next.angle=Number($(id).value)*Math.PI/180;else{const axis=id==='selection-width'?'width':'height';next[axis]=Number($(id).value)/METERS_PER_UNIT;if(pending?.type==='circle'){next.width=next[axis];next.height=next[axis];}}changeFrame(next);}
  function placeShape(type){
    if(drag)finish(true);const spacing=Number($('shape-spacing').value);if(!$('shape-spacing').checkValidity()){$('shape-spacing').reportValidity();return;}
    tool='select';svg.dataset.tool=tool;document.querySelectorAll('button[data-tool]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.tool===tool)));
    const shape=viewportShape(type,view.width*METERS_PER_UNIT,view.height*METERS_PER_UNIT),center={x:view.x+view.width/2,y:view.y+view.height/2};
    pending={type,points:shapeToLocalLoop(shape,spacing).map(p=>({x:center.x+p.x/METERS_PER_UNIT,y:center.y-p.y/METERS_PER_UNIT}))};selected=[];frame=G.bounds(pending.points);render();
  }
  function cancelShape(message=true){if(drag)finish(true);pending=null;selected=[];frame=null;render();if(message)notify('已取消图形放置，原轨迹未改变');}
  function addShape(){
    if(!pending||frameConflict())return;const join=joinLoops(points(),pending.points);if(!join){$('pending-warning').textContent='无法无交叉地接入环线，请将图形拖到其他空白处';return;}
    const before=clone(points()),added=join.order.map(i=>({...pending.points[i]})),position=join.after+1,next=clone(points());next.splice(position,0,...added);track().points=next;pending=null;selected=added.map((_,i)=>position+i);frame=G.bounds(editable());remember(before);render();notify('图形已添加到页面轨迹，可继续调整或撤销');
  }
  function loadTrack(key){if(drag)finish(true);pending=null;selected=[];frame=null;currentKey=key;const item=track();$('track-name').value=item.name;$('track-id').value=item.id;$('track-description').value=item.description;syncLibrary();render();fit();}
  function newTrack(){const index=nextTrack++,key='draft-'+index;tracks.set(key,{id:'draft_track_'+index,name:'未命名轨迹 '+index,description:'',points:[],undo:[],redo:[],dirty:true});loadTrack(key);notify('已新建空白轨迹，其他轨迹的修改仍保留');}
  function saveTrack(){if(pending||points().length<3){notify('至少需要 3 个节点，且先完成图形放置');return;}if(!$('track-name').value.trim()){notify('请填写轨迹名称');$('track-name').focus();return;}if(!/^[a-z0-9_-]+$/.test($('track-id').value)){notify('轨迹 ID 仅支持小写字母、数字、下划线和连字符');$('track-id').focus();return;}if([...tracks].some(([key,item])=>key!==currentKey&&item.id===$('track-id').value)){notify('该轨迹 ID 已在本页使用，请换一个 ID');$('track-id').focus();return;}track().dirty=false;syncLibrary();renderRoutePreview();render();notify('已保存在当前页面，刷新后恢复示例；未写入正式轨迹库');}
  svg.addEventListener('pointerdown',begin);svg.addEventListener('pointermove',update);svg.addEventListener('pointerup',event=>{if(drag?.id===event.pointerId)finish();});for(const event of ['pointercancel','lostpointercapture'])svg.addEventListener(event,()=>finish(true));window.addEventListener('blur',()=>finish(true));
  svg.addEventListener('wheel',event=>{event.preventDefault();zoom(event.deltaY<0 ? 0.9 : 1.1,getPosition(event));},{passive:false});
  document.querySelectorAll('button[data-tool]').forEach(button=>button.addEventListener('click',()=>setTool(button.dataset.tool)));document.querySelectorAll('[data-shape]').forEach(button=>button.addEventListener('click',()=>placeShape(button.dataset.shape)));
  $('editor-undo').addEventListener('click',()=>undo());$('editor-redo').addEventListener('click',()=>undo(true));$('editor-fit').addEventListener('click',fit);$('zoom-in').addEventListener('click',()=>zoom(.8));$('zoom-out').addEventListener('click',()=>zoom(1.25));$('editor-focus').addEventListener('click',()=>{$('editor-workspace').classList.toggle('focus-canvas');svg.focus({preventScroll:true});});
  $('select-all').addEventListener('click',selectAll);$('deselect').addEventListener('click',clearSelection);$('delete-selection').addEventListener('click',removeSelected);$('cancel-shape').addEventListener('click',()=>cancelShape());$('add-shape').addEventListener('click',addShape);
  for(const id of ['selection-width','selection-height','selection-angle'])$(id).addEventListener('change',()=>resizeSelection(id));$('rotate-left').addEventListener('click',()=>frame&&changeFrame({...frame,angle:frame.angle-Math.PI/12}));$('rotate-right').addEventListener('click',()=>frame&&changeFrame({...frame,angle:frame.angle+Math.PI/12}));
  $('shape-spacing').addEventListener('change',()=>{if(!pending)return;if(!$('shape-spacing').checkValidity()){$('shape-spacing').reportValidity();return;}const shape={type:pending.type,width:frame.width*METERS_PER_UNIT,height:frame.height*METERS_PER_UNIT,rotation:0};pending.points=shapeToLocalLoop(shape,Number($('shape-spacing').value)).map(p=>G.world(frame,p.x/METERS_PER_UNIT,-p.y/METERS_PER_UNIT));render();});
  $('new-track').addEventListener('click',newTrack);$('new-track-inline').addEventListener('click',newTrack);$('save-track').addEventListener('click',saveTrack);$('clear-track').addEventListener('click',()=>{if(points().length)$('clear-dialog').showModal();});$('confirm-clear').addEventListener('click',()=>{pending=null;selected=[];frame=null;setPoints([]);$('clear-dialog').close();notify('已清空当前轨迹，可以撤销');});
  for(const [id,key]of[['track-name','name'],['track-id','id'],['track-description','description']])$(id).addEventListener('input',()=>{track()[key]=$(id).value;changed();render();});
  $('use-track').addEventListener('click',()=>{if(points().length<3||pending)return;$('track-choice').value=currentKey;markStale();renderRoutePreview();location.hash='generate';});$('track-choice').addEventListener('change',()=>{markStale();renderRoutePreview();});$('editor-shortcuts').addEventListener('click',()=>$('shortcuts-dialog').showModal());
  document.addEventListener('keydown',event=>{
    if($('page-tracks').hidden||document.querySelector('dialog[open]')||event.target.closest('input,textarea,select,[contenteditable=true]'))return;
    const key=event.key.toLowerCase(),command=event.ctrlKey||event.metaKey;
    if(command&&key==='z'){event.preventDefault();undo(event.shiftKey);return;}if(command&&key==='y'){event.preventDefault();undo(true);return;}if(command&&key==='a'){event.preventDefault();selectAll();return;}
    if(event.key==='Escape'){if(drag)finish(true);else if(pending)cancelShape();else clearSelection();event.preventDefault();return;}
    if(event.key==='Enter'&&pending){event.preventDefault();addShape();return;}
    if(['Delete','Backspace'].includes(event.key)&&selected.length){event.preventDefault();removeSelected();return;}
    if(command||event.altKey)return;
    const hotkey={h:'pan',p:'draw',e:'erase',v:'select'}[key];if(hotkey){setTool(hotkey);event.preventDefault();return;}if(key==='f'){fit();event.preventDefault();return;}
    const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];if(delta&&frame){event.preventDefault();const step=event.shiftKey?10:1;changeFrame({...frame,x:frame.x+delta[0]*step,y:frame.y+delta[1]*step});}
  });
  window.addEventListener('hashchange',()=>{if($('page-tracks').hidden&&drag)finish(true);});
  syncLibrary();render();applyView();
  return {current:()=>summary(track()),get:key=>summary(tracks.get(key)||track())};
})();
renderRoutePreview();

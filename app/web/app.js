const $ = (s) => document.querySelector(s);
const state = {items: [], categories: [], taxonomy: {}, category: '全部', selected: null, editing: null, returnToDetail: null};
const statusNames = {active:'可使用',reference:'历史参考',archived:'已归档'};

function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),3200)}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});const result=await response.json();if(!response.ok)throw new Error(result.error||'操作失败');return result}
async function load(){try{const data=await api('/api/prompts');state.items=data.prompts;state.categories=data.categories;state.taxonomy=data.taxonomy;renderNav();renderOptions();renderTaxonomy();render()}catch(error){toast(error.message)}}
function renderSubcategory(selected=''){const select=$('#subcategorySelect');select.replaceChildren(new Option('无子类',''));(state.taxonomy[$('#categorySelect').value]||[]).forEach(name=>select.add(new Option(name,name)));select.value=[...select.options].some(o=>o.value===selected)?selected:''}
const taxonomyIcons={rename:'<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 14.5-.5 2 2-.5L15.5 6a1.4 1.4 0 0 0-2-2L4 14.5Z"/><path d="m11.7 5.8 2.5 2.5"/></svg>',delete:'<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 6h11M7 6V4.5h6V6m-7.5 0 .7 10h7.6l.7-10M8.5 9v4.5M11.5 9v4.5"/></svg>'};
let selectedTaxonomyCategory='';
function taxonomyButton(action,level,category,subcategory=''){
  const button=document.createElement('button');
  button.type='button';
  button.className='taxonomy-icon'+(action==='delete'?' taxonomy-icon--danger':'');
  button.innerHTML=taxonomyIcons[action];
  const label=`${action==='rename'?'重命名':'删除'}${level==='category'?'大类':'子类'}「${subcategory||category}」`;
  button.setAttribute('aria-label',label);
  button.title=label;
  button.onclick=()=>openTaxonomyAction(action,level,category,subcategory);
  return button;
}
function renderTaxonomy(){
  $('#taxonomyAction').hidden=true;taxonomyAction=null;
  $('#categoryForm').hidden=true;$('#subcategoryForm').hidden=true;
  if(!state.categories.includes(selectedTaxonomyCategory))selectedTaxonomyCategory=state.categories[0]||'';
  const list=$('#taxonomyList');list.replaceChildren();
  state.categories.forEach(category=>{
    const row=document.createElement('div');row.className='taxonomy-category'+(category===selectedTaxonomyCategory?' active':'');
    const select=document.createElement('button');select.type='button';select.className='taxonomy-category-name';select.textContent=category;select.setAttribute('aria-current',String(category===selectedTaxonomyCategory));
    select.onclick=()=>{selectedTaxonomyCategory=category;renderTaxonomy()};
    const actions=document.createElement('div');actions.className='taxonomy-item-actions';
    actions.append(taxonomyButton('rename','category',category),taxonomyButton('delete','category',category));
    row.append(select,actions);list.append(row);
  });
  const sublist=$('#taxonomySublist');sublist.replaceChildren();
  (state.taxonomy[selectedTaxonomyCategory]||[]).forEach(sub=>{
    const row=document.createElement('div');row.className='taxonomy-subcategory';
    const name=document.createElement('span');name.textContent=sub;
    const actions=document.createElement('div');actions.className='taxonomy-item-actions';
    actions.append(taxonomyButton('rename','subcategory',selectedTaxonomyCategory,sub),taxonomyButton('delete','subcategory',selectedTaxonomyCategory,sub));
    row.append(name,actions);sublist.append(row);
  });
  $('#taxonomyCategory').value=selectedTaxonomyCategory;
}
let taxonomyAction=null;
function renderTargets(){const form=$('#taxonomyAction');const category=form.elements.target_category.value;const sub=form.elements.target_subcategory;sub.replaceChildren(new Option('不选择子类',''));(state.taxonomy[category]||[]).filter(name=>taxonomyAction?.level!=='subcategory'||name!==taxonomyAction.subcategory).forEach(name=>sub.add(new Option(name,name)))}
function openTaxonomyAction(action,level,category,subcategory=''){taxonomyAction={action,level,category,subcategory};selectedTaxonomyCategory=category;renderTaxonomy();taxonomyAction={action,level,category,subcategory};const form=$('#taxonomyAction');form.hidden=false;form.reset();const used=state.items.filter(item=>item.category===category&&(level==='category'||item.subcategory===subcategory)).length;const subject=level==='category'?`大类「${category}」`:`子类「${subcategory}」`;$('#taxonomyActionTitle').textContent=`${action==='rename'?'重命名':'删除'}${subject}`;const help=$('#taxonomyActionHelp');help.hidden=!used;help.textContent=action==='rename'?`将更新 ${used} 条提示词的分类。`:`将迁移 ${used} 条提示词。`;$('#taxonomyNewNameLabel').hidden=action!=='rename';$('#taxonomyTargetCategoryLabel').hidden=action!=='delete'||!used||level==='subcategory';$('#taxonomyTargetSubcategoryLabel').hidden=action!=='delete'||!used;const target=form.elements.target_category;target.replaceChildren();const categories=level==='category'?state.categories.filter(value=>value!==category):[category];categories.forEach(value=>target.add(new Option(value,value)));renderTargets();const confirm=$('#taxonomyConfirm');confirm.classList.toggle('danger',action==='delete');confirm.textContent=action==='rename'?'保存名称':used?'迁移并删除':'删除分类';requestAnimationFrame(()=>form.scrollIntoView({block:'nearest'}));if(action==='rename')form.elements.name.focus();else if(used)form.elements.target_subcategory.focus();else confirm.focus()}
function renderNav(){const nav=$('#categories');nav.replaceChildren();['全部',...state.categories].forEach(name=>{const count=state.items.filter(x=>name==='全部'||x.category===name).length;const btn=document.createElement('button');btn.className='nav-item'+(state.category===name?' active':'');btn.innerHTML='<span></span><span class="nav-count"></span>';btn.firstChild.textContent=name;btn.lastChild.textContent=count;btn.onclick=()=>{state.category=name;renderNav();renderOptions();render()};nav.append(btn)})}
function renderOptions(){const select=$('#categorySelect');select.replaceChildren();state.categories.forEach(name=>{const option=document.createElement('option');option.value=option.textContent=name;select.append(option)});const subSelect=$('#subcategoryFilter');const previousSub=subSelect.value;subSelect.replaceChildren(new Option('全部子类','all'));[...new Set(state.items.filter(x=>state.category==='全部'||x.category===state.category).map(x=>x.subcategory).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh')).forEach(value=>subSelect.add(new Option(value,value)));subSelect.value=[...subSelect.options].some(o=>o.value===previousSub)?previousSub:'all'}
function excerpt(item){const text=item.body.replace(/[#*`>|\[\]]/g,'').replace(/\s+/g,' ').trim();return text.slice(0,125)+(text.length>125?'…':'')}
function visibleItems() {
  const query = $('#search').value.trim().toLocaleLowerCase();
  const status = $('#statusFilter').value;
  const subcategory = $('#subcategoryFilter').value;
  return state.items.filter(item =>
    (state.category === '全部' || item.category === state.category) &&
    (subcategory === 'all' || item.subcategory === subcategory) &&
    (status === 'all' || item.status === status) &&
    (!query || [item.title, item.category, item.subcategory, item.body]
      .join(' ').toLocaleLowerCase().includes(query))
  );
}

function promptRow(item) {
  const row = document.createElement('article');
  row.className = 'card';
  row.tabIndex = 0;
  row.setAttribute('role', 'button');
  row.setAttribute('aria-label', `查看 ${item.title}`);

  const title = document.createElement('h3');
  title.textContent = item.title;
  const summary = document.createElement('p');
  summary.textContent = excerpt(item);
  const meta = document.createElement('div');
  meta.className = 'card-top';
  const category = document.createElement('span');
  category.textContent = item.subcategory ? `${item.category} · ${item.subcategory}` : item.category;
  meta.append(category);
  if (item.status !== 'active') {
    const badge = document.createElement('span');
    badge.className = `badge badge--${item.status}`;
    badge.textContent = statusNames[item.status];
    meta.append(badge);
  }
  row.append(title, summary, meta);
  row.onclick = () => openDetail(item.id);
  row.onkeydown = event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openDetail(item.id);
    }
  };
  return row;
}

function render() {
  const items = visibleItems();
  $('#viewTitle').textContent = state.category === '全部' ? '全部提示词' : state.category;
  $('#resultCount').textContent = `${items.length} 条`;
  $('#empty').hidden = items.length > 0;
  $('#cards').replaceChildren(...items.map(promptRow));
}
function renderAttachments(body){const box=$('#attachments');box.replaceChildren();const names=[...body.matchAll(/图片和附件\/([^\s)]+(?:%20[^\s)]+)*)/g)].map(match=>{try{return decodeURIComponent(match[1])}catch{return match[1]}});[...new Set(names)].forEach(name=>{if(name.includes('/')||name.includes('\\'))return;const url='/attachments/'+encodeURIComponent(name);const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener';if(/\.(png|jpe?g|gif|webp)$/i.test(name)){const img=document.createElement('img');img.src=url;img.alt='';link.append(img)}const label=document.createElement('span');label.textContent=name;link.append(label);box.append(link)})}
function setReaderMode(mode){const rendered=mode==='rendered';$('#detailBody').hidden=!rendered;$('#detailRaw').hidden=rendered;$('#renderedViewBtn').classList.toggle('active',rendered);$('#rawViewBtn').classList.toggle('active',!rendered);$('#renderedViewBtn').setAttribute('aria-pressed',String(rendered));$('#rawViewBtn').setAttribute('aria-pressed',String(!rendered))}
function openDetail(id){const item=state.items.find(x=>x.id===id);if(!item)return;state.selected=id;$('#detailCategory').textContent=item.subcategory?`${item.category} · ${item.subcategory}`:item.category;$('#detailTitle').textContent=item.title;$('#detailStatus').hidden=item.status==='active';$('#detailStatus').textContent=statusNames[item.status];renderPromptMarkdown(item.body,$('#detailBody'));$('#detailRaw').textContent=item.body;setReaderMode('rendered');renderAttachments(item.body);$('#archiveBtn').textContent=item.status==='archived'?'恢复':'归档';$('#detailDialog').showModal()}
function openForm(item=null){state.editing=item?.id??null;if(!item)state.returnToDetail=null;$('#formTitle').textContent=item?'编辑提示词':'新增提示词';const form=$('#promptForm');form.reset();form.elements.title.value=item?.title||'';form.elements.category.value=item?.category||state.categories[0]||'';renderSubcategory(item?.subcategory||'');form.elements.status.value=item?.status||'active';form.elements.body.value=item?.body||'';$('#editDialog').showModal();form.elements.title.focus()}
$('#categorySelect').onchange=()=>renderSubcategory();
$('#taxonomyBtn').onclick=()=>{renderTaxonomy();$('#taxonomyDialog').showModal()};
$('#addCategoryBtn').onclick=()=>{$('#taxonomyAction').hidden=true;taxonomyAction=null;$('#subcategoryForm').hidden=true;const form=$('#categoryForm');form.hidden=false;form.elements.category.focus()};
$('#addSubcategoryBtn').onclick=()=>{$('#taxonomyAction').hidden=true;taxonomyAction=null;$('#categoryForm').hidden=true;const form=$('#subcategoryForm');form.elements.category.value=selectedTaxonomyCategory;form.hidden=false;form.elements.subcategory.focus()};
document.querySelectorAll('[data-cancel-add]').forEach(button=>button.onclick=()=>{const form=button.closest('form');form.reset();form.hidden=true});
$('#categoryForm').onsubmit=async(e)=>{e.preventDefault();try{await api('/api/taxonomy',{method:'POST',body:JSON.stringify({category:e.target.elements.category.value})});e.target.reset();await load();toast('大类已添加')}catch(error){toast(error.message)}};
$('#subcategoryForm').onsubmit=async(e)=>{e.preventDefault();try{await api('/api/taxonomy',{method:'POST',body:JSON.stringify({category:e.target.elements.category.value,subcategory:e.target.elements.subcategory.value})});const category=e.target.elements.category.value;e.target.reset();await load();e.target.elements.category.value=category;toast('子类已添加')}catch(error){toast(error.message)}};
$('#taxonomyTargetCategory').onchange=renderTargets;
$('#taxonomyCancel').onclick=()=>{$('#taxonomyAction').hidden=true;taxonomyAction=null};
$('#taxonomyAction').onsubmit=async(e)=>{e.preventDefault();if(!taxonomyAction)return;const form=e.target;const used=state.items.filter(item=>item.category===taxonomyAction.category&&(taxonomyAction.level==='category'||item.subcategory===taxonomyAction.subcategory)).length;const payload={...taxonomyAction,name:form.elements.name.value,target_category:used?form.elements.target_category.value:'',target_subcategory:used?form.elements.target_subcategory.value:''};const button=$('#taxonomyConfirm');button.disabled=true;try{const result=await api('/api/taxonomy',{method:taxonomyAction.action==='rename'?'PATCH':'DELETE',body:JSON.stringify(payload)});form.hidden=true;taxonomyAction=null;if(state.category===payload.category&&payload.level==='category')state.category=payload.action==='rename'?payload.name:'全部';if(payload.level==='category')selectedTaxonomyCategory=payload.action==='rename'?payload.name:(payload.target_category||'');await load();toast(payload.action==='rename'?'分类已重命名':`分类已删除，迁移 ${result.moved} 条`)}catch(error){toast(error.message)}finally{button.disabled=false}};
$('#newBtn').onclick=()=>openForm();$('#editBtn').onclick=()=>{const item=state.items.find(x=>x.id===state.selected);$('#detailDialog').close();state.returnToDetail=item.id;openForm(item)};
$('#renderedViewBtn').onclick=()=>setReaderMode('rendered');
$('#rawViewBtn').onclick=()=>setReaderMode('raw');
$('#choosePromptFile').onclick=()=>$('#promptFile').click();
$('#promptFile').onchange=async(e)=>{const file=e.target.files?.[0];if(!file)return;const form=$('#promptForm');form.elements.body.value=await file.text();if(!form.elements.title.value.trim())form.elements.title.value=file.name.replace(/\.(md|txt)$/i,'');toast('正文已载入');e.target.value=''};
$('#archiveBtn').onclick=async()=>{const item=state.items.find(x=>x.id===state.selected);const next={...item,status:item.status==='archived'?'active':'archived'};try{await api(`/api/prompts/${item.id}`,{method:'PUT',body:JSON.stringify(next)});$('#detailDialog').close();await load();toast(next.status==='archived'?'已归档':'已恢复')}catch(error){toast(error.message)}};
$('#deleteBtn').onclick=()=>{
  const item=state.items.find(x=>x.id===state.selected);
  if(!item)return;
  $('#deletePromptTitle').textContent=`「${item.title}」`;
  $('#detailDialog').close();
  $('#deleteDialog').showModal();
};
let deletingPrompt=false;
$('#deleteDialog').addEventListener('cancel',event=>{if(deletingPrompt)event.preventDefault()});
$('#deleteDialog').addEventListener('close',()=>{
  if(state.selected!==null)openDetail(state.selected);
});
$('#confirmDeleteBtn').onclick=async()=>{
  const item=state.items.find(x=>x.id===state.selected);
  if(!item)return;
  const button=$('#confirmDeleteBtn');
  const cancel=$('#deleteDialog [data-close]');
  deletingPrompt=true;
  button.disabled=true;
  cancel.disabled=true;
  try{
    await api(`/api/prompts/${item.id}`,{method:'DELETE'});
    state.selected=null;
    $('#deleteDialog').close();
    await load();
    toast('提示词已删除');
  }catch(error){toast(error.message)}
  finally{deletingPrompt=false;button.disabled=false;cancel.disabled=false}
};
$('#copyBtn').onclick=async()=>{try{await navigator.clipboard.writeText(state.items.find(x=>x.id===state.selected).body);toast('正文已复制')}catch{toast('复制失败，请手动选择正文复制')}};
$('#promptForm').onsubmit=async(e)=>{e.preventDefault();const form=e.target;const value={title:form.elements.title.value,category:form.elements.category.value,subcategory:form.elements.subcategory.value,status:form.elements.status.value,body:form.elements.body.value};const button=form.querySelector('[type=submit]');button.disabled=true;try{const path=state.editing?`/api/prompts/${state.editing}`:'/api/prompts';const result=await api(path,{method:state.editing?'PUT':'POST',body:JSON.stringify(value)});state.returnToDetail=null;$('#editDialog').close();await load();toast('提示词已保存');openDetail(result.id)}catch(error){toast(error.message)}finally{button.disabled=false}};
function restoreDetailAfterEdit(){if(state.returnToDetail!==null){const id=state.returnToDetail;state.returnToDetail=null;openDetail(id)}}
$('#editDialog').addEventListener('close',restoreDetailAfterEdit);
document.querySelectorAll('[data-close]').forEach(btn=>btn.onclick=()=>{document.getElementById(btn.dataset.close).close();if(btn.dataset.close==='editDialog')restoreDetailAfterEdit()});['search','subcategoryFilter','statusFilter'].forEach(id=>$('#'+id).addEventListener(id==='search'?'input':'change',render));
$('#exportBtn').onclick=()=>{window.location.href='/api/backup'};
$('#importBtn').onclick=()=>$('#importFile').click();
$('#importFile').onchange=async(e)=>{const file=e.target.files?.[0];if(!file)return;try{const data=JSON.parse(await file.text());const result=await api('/api/backup',{method:'POST',body:JSON.stringify(data)});await load();toast(`导入完成，新增 ${result.added} 条`)}catch(error){toast(error.message)}e.target.value=''};
load();
setInterval(()=>{if(!document.hidden&&!['editDialog','detailDialog','taxonomyDialog','deleteDialog'].some(id=>$('#'+id).open))load()},5000);

/* Offline, DOM-based Markdown reader. Content is never inserted as raw HTML. */
(function(){
  const text=(value)=>document.createTextNode(value);
  const make=(tag)=>document.createElement(tag);
  function safeUrl(raw,image=false){
    const value=raw.trim().replace(/^<|>$/g,'');
    if(/^图片和附件\//.test(value)){
      const name=value.slice('图片和附件/'.length);
      if(name&&!name.includes('/')&&!name.includes('\\'))return '/attachments/'+encodeURIComponent(name);
    }
    if(image)return null; // Never fetch remote images from a private, offline library.
    if(/^(https?:|mailto:)/i.test(value))return value;
    return null;
  }
  function inline(source,parent,depth=0){
    if(depth>8){parent.append(text(source));return}
    const pattern=/(!?\[([^\]\n]*)\]\(([^)\n]+)\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*|__([^_\n]+)__|~~([^~\n]+)~~|(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_))/g;
    let start=0,match;
    while((match=pattern.exec(source))){
      if(match.index>start)parent.append(text(source.slice(start,match.index)));
      const whole=match[0];
      if(match[2]!==undefined){
        const isImage=whole.startsWith('!');
        const url=safeUrl(match[3],isImage);
        if(!url){parent.append(text(whole))}
        else if(isImage){const img=make('img');img.src=url;img.alt=match[2];img.loading='lazy';parent.append(img)}
        else{const a=make('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.append(text(match[2]||url));parent.append(a)}
      }else if(match[4]!==undefined){const node=make('code');node.append(text(match[4]));parent.append(node)}
      else{const tag=(match[5]!==undefined||match[6]!==undefined)?'strong':match[7]!==undefined?'del':'em';const node=make(tag);inline(match[5]??match[6]??match[7]??match[8]??match[9],node,depth+1);parent.append(node)}
      start=pattern.lastIndex;
    }
    if(start<source.length)parent.append(text(source.slice(start)));
  }
  const fence=(line)=>/^ {0,3}(`{3,}|~{3,})/.exec(line);
  const heading=(line)=>/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
  const unordered=(line)=>/^\s{0,3}[-*+]\s+(.+)$/.exec(line);
  const ordered=(line)=>/^\s{0,3}\d+[.)]\s+(.+)$/.exec(line);
  const divider=(line)=>/^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);
  const quote=(line)=>/^\s{0,3}>\s?(.*)$/.exec(line);
  const tableRule=(line)=>/^\s*\|?\s*:?-{3,}:?(\s*\|\s*:?-{3,}:?)*\s*\|?\s*$/.test(line);
  function cells(line){return line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(x=>x.trim())}
  function blockStart(line){return Boolean(fence(line)||heading(line)||unordered(line)||ordered(line)||divider(line)||quote(line))}
  function blocks(source,parent,depth=0){
    const lines=source.replace(/\r\n?/g,'\n').split('\n');
    for(let i=0;i<lines.length;){
      const line=lines[i];
      if(!line.trim()){i++;continue}
      const opening=fence(line);
      if(opening){
        const code=[];const marker=opening[1];i++;
        while(i<lines.length&&!new RegExp('^ {0,3}'+marker[0]+'{'+marker.length+',}\\s*$').test(lines[i]))code.push(lines[i++]);
        if(i<lines.length)i++;
        const pre=make('pre'),inner=make('code');inner.append(text(code.join('\n')));pre.append(inner);parent.append(pre);continue;
      }
      const h=heading(line);
      if(h){const el=make('h'+h[1].length);inline(h[2],el);parent.append(el);i++;continue}
      if(divider(line)){parent.append(make('hr'));i++;continue}
      const q=quote(line);
      if(q){const contents=[];while(i<lines.length){const item=quote(lines[i]);if(!item)break;contents.push(item[1]);i++}const el=make('blockquote');if(depth<5)blocks(contents.join('\n'),el,depth+1);else el.append(text(contents.join('\n')));parent.append(el);continue}
      const list=unordered(line)||ordered(line);
      if(list){const isOrdered=Boolean(ordered(line));const el=make(isOrdered?'ol':'ul');while(i<lines.length){const item=(isOrdered?ordered:unordered)(lines[i]);if(!item)break;const li=make('li');inline(item[1],li);el.append(li);i++}parent.append(el);continue}
      if(line.includes('|')&&i+1<lines.length&&tableRule(lines[i+1])){
        const table=make('table'),thead=make('thead'),tbody=make('tbody'),head=make('tr');
        cells(line).forEach(value=>{const th=make('th');inline(value,th);head.append(th)});thead.append(head);table.append(thead);i+=2;
        while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){const row=make('tr');cells(lines[i++]).forEach(value=>{const td=make('td');inline(value,td);row.append(td)});tbody.append(row)}
        table.append(tbody);parent.append(table);continue;
      }
      const chunk=[line];i++;
      while(i<lines.length&&lines[i].trim()&&!blockStart(lines[i])&&!(lines[i].includes('|')&&i+1<lines.length&&tableRule(lines[i+1])))chunk.push(lines[i++]);
      const p=make('p');chunk.forEach((part,index)=>{if(index)p.append(make('br'));inline(part,p)});parent.append(p);
    }
  }
  window.renderPromptMarkdown=(source,target)=>{
    target.replaceChildren();
    const raw=String(source);
    // Some legacy prompts were stored as one large fenced Markdown example.
    // Unwrap only a fence surrounding the entire body; the raw view remains exact.
    const outer=/^\s*```(?:md|markdown)\s*\n([\s\S]*?)\n```\s*$/i.exec(raw);
    blocks(outer?outer[1]:raw,target);
  };
})();

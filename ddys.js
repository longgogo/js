/*
 * ZIP0 影视  (https://zip0.com)
 * ------------------------------------------------------------------
 * 饭团(FYT) / DRPY 通用 JS 规则源
 *
 * 站点采用 TanStack Start (SSR) 架构，页面无静态 HTML，
 * 全部数据由 TanStack Server Function 以 seroval 序列化 RPC 返回。
 * 因此本源不使用 CSS 选择器，而是直接复现其 RPC 协议：
 *
 *   GET https://zip0.com/_serverFn/<64位函数ID>?payload=<seroval({data:...})>
 *   Header: x-tsr-serverFn: true  (+ 完整浏览器头，否则 403)
 *
 * 三个核心 Server Function：
 *   首页/最近更新 : b42ee085...  ->  movie / tv / short / variety / anime 五个分区，各 12 条
 *   搜索         : 0ea055b1...  ->  payload = {data:{query:'关键词'}}  聚合 10 条线路
 *   详情+剧集     : 75b7f04d...  ->  payload = {data:{id:'', source:''}} 返回 m3u8 直链
 *
 * 说明：
 *   - 首页函数不响应任何参数、无分页，故各分类固定 12 条最新。
 *   - 搜索函数无分页，一次性返回全线路结果，本源已按「标题+年份」做归一化去重。
 *   - 详情返回单一线路的剧集，播放源名称显示为该线路名（线路 1 ~ 线路 10）。
 * ------------------------------------------------------------------
 */

// 公共函数库（DRPY/饭团 js: 模式下每段会被独立求值，故以字符串形式复用）
var Z0_BASE = [
    "var Z0H='https://zip0.com';",
    "var Z0HF='b42ee085174093515a801f91174a8e544266b579c62db3cecc6d13f99a17dd1d';",
    "var Z0SF='0ea055b1bc0887b5073a2593859b23183a23130e03aa0cd4acea5e53c72ee834';",
    "var Z0DF='75b7f04db7f68591c58cd4cbf1a827b99ed16ccbe2e203c1af2d34358cab97df';",
    "var Z0HD={'x-tsr-serverFn':'true','Accept':'application/json, text/plain, */*','Accept-Language':'zh-CN,zh;q=0.9','Referer':'https://zip0.com/','Origin':'https://zip0.com','Sec-Fetch-Site':'same-origin','Sec-Fetch-Mode':'cors','Sec-Fetch-Dest':'empty','User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'};",
    // --- seroval 序列化：{t:类型, i:自增值, p:{k:键, v:值}, o:0} ---
    "function Z0SV(v){var c={i:0};function en(x){var i,r;if(typeof x==='string')return{t:1,s:x};if(typeof x==='number')return{t:0,s:x};if(x instanceof Array){r=[];for(i=0;i<x.length;i++)r.push(en(x[i]));return{t:9,i:c.i++,a:r,o:0};}if(typeof x==='object'&&x!==null){var k=[];for(var kk in x){k.push(kk);}r=[];for(i=0;i<k.length;i++)r.push(en(x[k[i]]));return{t:10,i:c.i++,p:{k:k,v:r},o:0};}return{t:1,s:String(x)};}return JSON.stringify({t:en(v),f:127,m:[]});}",
    "function Z0DC(s){try{return decodeURIComponent(s);}catch(e){return s;}}",
    "function Z0Q(u,n){var i=u.indexOf('?');if(i<0)return'';var a=u.substring(i+1).split('&');for(var k=0;k<a.length;k++){var p=a[k].split('=');if(p[0]===n)return Z0DC(p[1]||'');}return'';}",
    "function Z0RQ(u){try{return request(u,{headers:Z0HD,timeout:25000});}catch(e){try{return request(u,Z0HD);}catch(e2){return request(u);}}}",
    "function Z0CALL(fid,arg){return Z0RQ(Z0H+'/_serverFn/'+fid+'?payload='+encodeURIComponent(Z0SV({data:arg})));}",
    // --- seroval 反序列化：直接 JSON.parse 后递归还原 ---
    "function Z0VAL(n){var i,r;if(n===null||n===undefined)return'';if(typeof n==='number'||typeof n==='string'||typeof n==='boolean')return n;if(n instanceof Array){r=[];for(i=0;i<n.length;i++)r.push(Z0VAL(n[i]));return r;}if(typeof n==='object'){if(n.p&&n.p.k){r={};for(i=0;i<n.p.k.length;i++)r[n.p.k[i]]=Z0VAL(n.p.v[i]);return r;}if(n.a){r=[];for(i=0;i<n.a.length;i++)r.push(Z0VAL(n.a[i]));return r;}if(typeof n.s!=='undefined')return Z0VAL(n.s);return'';}return'';}",
    "function Z0WALK(n,out,mk){var i;if(n===null||typeof n!=='object')return;if(n instanceof Array){for(i=0;i<n.length;i++)Z0WALK(n[i],out,mk);return;}if(n.p&&n.p.k){var ok=true;for(i=0;i<mk.length;i++){if(n.p.k.indexOf(mk[i])<0){ok=false;break;}}if(ok){var o={};for(i=0;i<n.p.k.length;i++)o[n.p.k[i]]=Z0VAL(n.p.v[i]);out.push(o);}Z0WALK(n.p.v,out,mk);return;}if(n.a){Z0WALK(n.a,out,mk);return;}}",
    "function Z0PICK(blob,mk){var out=[];var root=null;try{root=JSON.parse(blob);}catch(e){return out;}Z0WALK(root,out,mk);return out;}",
    // --- 首页按 movie/tv/short/variety/anime 五分区拆分 ---
    "function Z0SEC(root,names){var res={};var found=null;function fd(n){var i;if(n===null||typeof n!=='object')return;if(n instanceof Array){for(i=0;i<n.length;i++)fd(n[i]);return;}if(n.p&&n.p.k){if(n.p.k.length===names.length&&n.p.k.join(',')===names.join(',')){found=n;return;}fd(n.p.v);return;}if(n.a){fd(n.a);return;}}fd(root);if(!found)return res;for(var i=0;i<names.length;i++){var arr=[];Z0WALK(found.p.v[i],arr,['id','source']);res[names[i]]=arr;}return res;}",
    // --- 标题归一化：仅保留中日韩字符与字母数字，用于跨线路去重 ---
    "function Z0NORM(t){var s='',i=0,c;for(;i<t.length;i++){c=t.charCodeAt(i);if(c>=12352){s+=t.charAt(i);}else if((c>=48&&c<=57)||(c>=65&&c<=90)||(c>=97&&c<=122)){s+=t.charAt(i);}}return s;}",
    // --- 播放地址：仅对非 ASCII 字符做百分号编码(部分线路的分集路径含中文)，保留 : / ? & = # ---
    "function Z0ENC(u){var s='',i=0,c;for(;i<u.length;i++){c=u.charCodeAt(i);if(c<128){s+=u.charAt(i);}else{s+=encodeURIComponent(u.charAt(i));}}return s;}",
    // --- 列表项 -> VODS ---
    "function Z0MK(o){return{url:Z0H+'/_serverFn/'+Z0DF+'?fid='+encodeURIComponent(o.id)+'&fs='+encodeURIComponent(o.source),vod_id:o.id,vod_name:o.title,vod_pic:o.poster,vod_remarks:o.remarks,vod_year:o.year,vod_tag:o.category};}"
].join("\n");

var Z0_HOME_BODY = [
    "var sec=Z0Q(input,'c');if(!sec)sec='home';",
    "var pg=parseInt(Z0Q(input,'p'),10);if(!pg||pg<1)pg=1;",
    "var arr=[];",
    "if(pg===1){",
    "  var blob=Z0CALL(Z0HF,{});",
    "  if(sec==='home'){arr=Z0PICK(blob,['id','source']);}",
    "  else{var root=null;try{root=JSON.parse(blob);}catch(e){root=null;}",
    "    var m=Z0SEC(root,['movie','tv','short','variety','anime']);",
    "    var sub=m[sec]||[];for(var i=0;i<sub.length;i++)arr.push(sub[i]);}",
    "}",
    "var d=[];for(var j=0;j<arr.length;j++){if(arr[j]&&arr[j].id)d.push(Z0MK(arr[j]));}",
    "VODS=d;",
    "if(typeof setResult==='function'){setResult(d);}"
].join("\n");

var Z0_REC_BODY = [
    "var sec=Z0Q(input,'c');if(!sec)sec='home';",
    "var blob=Z0CALL(Z0HF,{});",
    "var arr=[];",
    "if(sec==='home'){arr=Z0PICK(blob,['id','source']);}",
    "else{var root=null;try{root=JSON.parse(blob);}catch(e){root=null;}",
    "  var m=Z0SEC(root,['movie','tv','short','variety','anime']);",
    "  var sub=m[sec]||[];for(var i=0;i<sub.length;i++)arr.push(sub[i]);}",
    "var d=[];for(var j=0;j<arr.length;j++){if(arr[j]&&arr[j].id)d.push(Z0MK(arr[j]));}",
    "VODS=d;",
    "if(typeof setResult==='function'){setResult(d);}"
].join("\n");

var Z0_SEARCH_BODY = [
    "var kw=Z0Q(input,'q');",
    "if(!kw){var qi=input.indexOf('?');kw=(qi<0)?input:'';}",
    "var arr=[];",
    "if(kw){var blob=Z0CALL(Z0SF,{query:kw});arr=Z0PICK(blob,['id','source']);}",
    "var seen={};var d=[];",
    "for(var j=0;j<arr.length;j++){",
    "  var o=arr[j];if(!o||!o.id||!o.source)continue;",
    "  var key=Z0NORM(o.title||'')+'|'+(o.year||'');",
    "  if(seen[key])continue;",
    "  seen[key]=1;",
    "  d.push(Z0MK(o));",
    "}",
    "VODS=d;",
    "if(typeof setResult==='function'){setResult(d);}"
].join("\n");

var Z0_DETAIL_BODY = [
    "var id=Z0Q(input,'fid');var src=Z0Q(input,'fs');",
    "if((!id||!src)&&input.indexOf('@')>0){var tail=input.substring(input.lastIndexOf('/')+1);var pp=tail.split('@');id=pp[0];src=pp[1];}",
    "var V={vod_id:String(id||''),vod_name:'',vod_pic:'',vod_year:'',vod_area:'',vod_remarks:'',vod_actor:'',vod_director:'',vod_content:'',vod_play_from:'',vod_play_url:''};",
    "if(id&&src){",
    "  var blob=Z0CALL(Z0DF,{id:String(id),source:String(src)});",
    "  var det=Z0PICK(blob,['id','source'])[0]||{};",
    "  var eps=Z0PICK(blob,['name','url']);",
    "  var pu=[];",
    "  for(var i=0;i<eps.length;i++){if(eps[i].url){pu.push((eps[i].name||('第'+(i+1)+'集'))+'$'+Z0ENC(eps[i].url));}}",
    "  V={vod_id:String(id),vod_name:det.title||'',vod_pic:det.poster||'',vod_year:det.year||'',vod_area:det.area||'',vod_remarks:det.remarks||'',vod_actor:det.actors||'',vod_director:det.director||'',vod_content:det.description||'',vod_play_from:det.sourceName||String(src),vod_play_url:pu.join('#')};",
    "}",
    "VOD=V;"
].join("\n");

var rule = {
    title: 'ZIP0影视',
    host: 'https://zip0.com',
    homeUrl: '/_serverFn/b42ee085174093515a801f91174a8e544266b579c62db3cecc6d13f99a17dd1d?c=home&p=1',
    url: '/_serverFn/b42ee085174093515a801f91174a8e544266b579c62db3cecc6d13f99a17dd1d?c=fyclass&p=fypage',
    class_name: '首页&电影&电视剧&短剧&综艺&动漫',
    class_url: 'home&movie&tv&short&variety&anime',
    searchUrl: '/_serverFn/0ea055b1bc0887b5073a2593859b23183a23130e03aa0cd4acea5e53c72ee834?q=**',
    searchable: 2,
    quickSearch: 0,
    filterable: 0,
    double: false,
    play_parse: false,
    timeout: 25000,
    lazy: '',
    headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': 'https://zip0.com/'
    },
    推荐: 'js:\n' + Z0_BASE + '\n' + Z0_REC_BODY,
    一级: 'js:\n' + Z0_BASE + '\n' + Z0_HOME_BODY,
    二级: 'js:\n' + Z0_BASE + '\n' + Z0_DETAIL_BODY,
    搜索: 'js:\n' + Z0_BASE + '\n' + Z0_SEARCH_BODY
};

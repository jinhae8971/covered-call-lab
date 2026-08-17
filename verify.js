/* 경제적자유 랩 — 신규 디자인 회귀 검증 (jsdom) */
const fs = require('fs');
const P = '/sessions/youthful-blissful-hamilton/mnt/투자/covered-call-lab/dashboard.html';
const { JSDOM } = require('/tmp/node_modules/jsdom');
let pass=0, fail=0;
const ok=(n,c,x)=>{ if(c) pass++; else { fail++; console.log('  FAIL  '+n+(x?'  ← '+x:'')); } };

const charts={};
class ChartStub{
  constructor(cv,cfg){ this.canvas=cv; this.config=cfg; this.data=cfg.data;
    this.options=cfg.options||{}; this.plugins=cfg.plugins||[]; charts[cv&&cv.id]=this; }
  destroy(){} update(){} }
ChartStub.defaults={color:'',borderColor:'',font:{family:''}};
ChartStub.getChart=id=>charts[id]||null;
ChartStub.register=()=>{};

const CTX={save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillRect(){},
  fillText(){},setLineDash(){},measureText:()=>({width:40})};

const dom=new JSDOM(fs.readFileSync(P,'utf8'),{runScripts:'outside-only',pretendToBeVisual:true,url:'https://example.test/'});
const w=dom.window, d=w.document;
w.Chart=ChartStub;
w.HTMLCanvasElement.prototype.getContext=()=>CTX;

let bootErr=null;
try{ [...d.querySelectorAll('script')].filter(s=>!s.src).forEach(s=>w.eval(s.textContent)); }
catch(e){ bootErr=e; }
console.log('── 부팅 ──');
ok('인라인 스크립트 오류 없음', !bootErr, bootErr&&bootErr.message);
if(bootErr){ console.log(bootErr.stack.split('\n').slice(0,8).join('\n')); process.exit(1); }

console.log('── 셸 ──');
['pane-research','pane-portfolio','ccbadge','pfbadge','thbtn','thlb','thhint','gen','cnt','fxm']
  .forEach(id=>ok('#'+id+' 존재', !!d.getElementById(id)));
ok('.app 셸 존재', !!d.querySelector('.app'));
ok('다크가 기본 테마', d.documentElement.getAttribute('data-theme')!=='light');
ok('research 페인 활성', d.getElementById('pane-research').classList.contains('on'));
ok('portfolio 페인 비활성', !d.getElementById('pane-portfolio').classList.contains('on'));
ok('#ccbadge 종목 수', /^\d+종$/.test(d.getElementById('ccbadge').textContent.trim()), d.getElementById('ccbadge').textContent);
ok('#thlb 라벨 채워짐', d.getElementById('thlb').textContent.trim().length>0);

console.log('── KPI ──');
const K=d.getElementById('kpis');
ok('.khero 렌더', !!K.querySelector('.khero'));
ok('히어로 2칸', K.querySelectorAll('.khero .khc').length===2, K.querySelectorAll('.khero .khc').length);
ok('.rkb 배지 2개', K.querySelectorAll('.rkb').length===2);
ok('.kdiv 구분선', !!K.querySelector('.kdiv'));
ok('.ksm 참고지표 5칸', K.querySelectorAll('.ksm .kpi').length===5, K.querySelectorAll('.ksm .kpi').length);
const hv=[...K.querySelectorAll('.khero .v')].map(e=>e.textContent.trim());
ok('히어로 값 부호+숫자', hv.every(t=>/^[+−]\d/.test(t)), hv.join(' | '));
ok('히어로 pos/neg 클래스', [...K.querySelectorAll('.khero .v')].every(e=>e.classList.contains('pos')||e.classList.contains('neg')));

console.log('── 계보 스파인 ──');
ok('#spinebars 4칸', d.querySelectorAll('#spinebars .bc').length===4, d.querySelectorAll('#spinebars .bc').length);
const pts=d.getElementById('spineln').getAttribute('points');
ok('#spineln 4점', pts.trim().split(/\s+/).length===4, pts);
ok('스파인 y 유한값', pts.trim().split(/\s+/).every(p=>Number.isFinite(+p.split(',')[1])), pts);
ok('#genrow 4장', d.querySelectorAll('#genrow .gen').length===4, d.querySelectorAll('#genrow .gen').length);
ok('계보 카드 지표 4개', [...d.querySelectorAll('#genrow .gen')].every(g=>g.querySelectorAll('.mg > div').length===4));
ok('#genrow2 축 4종', d.querySelectorAll('#genrow2 .axpill').length===4, d.querySelectorAll('#genrow2 .axpill').length);

console.log('── 리서치 표 ──');
const th=[...d.querySelectorAll('#tbl thead th')];
ok('thead 7열', th.length===7, th.length);
const sum=[...d.querySelectorAll('#tbl tr.sum')], det=[...d.querySelectorAll('#tbl tr.det')];
ok('요약행 50+', sum.length>50, sum.length);
ok('요약행=상세행', sum.length===det.length, sum.length+' vs '+det.length);
ok('요약행 7셀', sum.every(t=>t.children.length===7));
ok('상세행 colspan=7', det.every(t=>t.querySelector('td').getAttribute('colspan')==='7'));
ok('상세행 기본 숨김', det.every(t=>t.hasAttribute('hidden')));
ok('상세행 dgrid 3그룹', det.every(t=>t.querySelectorAll('.dgrid > div').length===3));
ok('상세행 판정문', det.every(t=>t.querySelector('.dv-verdict').textContent.trim().length>10));
ok('.nmc 티커+시장', sum.every(t=>!!t.querySelector('.nmc .tk')&&!!t.querySelector('.nmc .mkt')));
ok('.scv 점수', sum.every(t=>!!t.querySelector('.scv')));
ok('.bar-mini 바', sum.every(t=>!!t.querySelector('.bar-mini i')));
ok('점수 바 폭 0~100%', sum.every(t=>{const v=parseFloat(t.querySelector('.bar-mini i').style.width);return !Number.isFinite(v)||(v>=0&&v<=100.001);}));
ok('.exv 초과수익', sum.every(t=>!!t.querySelector('.exv')));
ok('.exb 비교대상', sum.every(t=>!!t.querySelector('.exb')));
ok('.chev 표식', sum.every(t=>!!t.querySelector('.chev i')));
ok('#shown 형식', /^\d+종 표시$/.test(d.getElementById('shown').textContent), d.getElementById('shown').textContent);
ok('#shown = 행수', parseInt(d.getElementById('shown').textContent,10)===sum.length);

console.log('── 행 펼치기 ──');
const clk=el=>el.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
clk(sum[0]);
ok('클릭 → 상세 노출', !det[0].hasAttribute('hidden'));
ok('클릭 → tr.open', sum[0].classList.contains('open'));
clk(sum[0]);
ok('재클릭 → 접힘', det[0].hasAttribute('hidden'));
ok('open 제거', !sum[0].classList.contains('open'));
const AT=d.getElementById('allTgl');
clk(AT);
ok('전체 펼치기', [...d.querySelectorAll('#tbl tr.det')].every(t=>!t.hasAttribute('hidden')));
ok('라벨 = 전체 접기', AT.textContent.trim()==='전체 접기', AT.textContent);
clk(th[3]);
ok('정렬 후 펼침 유지', [...d.querySelectorAll('#tbl tr.det')].every(t=>!t.hasAttribute('hidden')));
clk(AT);
ok('전체 접기', [...d.querySelectorAll('#tbl tr.det')].every(t=>t.hasAttribute('hidden')));
ok('정렬 화살표 1개', d.querySelectorAll('#tbl thead .ar').length===1, d.querySelectorAll('#tbl thead .ar').length);

console.log('── 필터 ──');
const N0=d.querySelectorAll('#tbl tr.sum').length;
clk(d.querySelector('.chip[data-f="mkt"][data-v="KR"]'));
const kr=[...d.querySelectorAll('#tbl tr.sum')];
ok('KR 필터 축소', kr.length>0&&kr.length<N0, kr.length+'/'+N0);
ok('KR 결과 정합', kr.every(t=>t.querySelector('.mkt').textContent==='KR'||t.classList.contains('bm')));
clk(d.querySelector('.chip[data-f="mkt"][data-v="ALL"]'));
ok('ALL 복귀', d.querySelectorAll('#tbl tr.sum').length===N0);
const bc=d.querySelector('.chip[data-f="bm"]');
ok('bm 칩 = 지수 포함', bc.textContent.trim()==='지수 포함', bc.textContent);
clk(bc);
ok('토글 = 지수 제외', bc.textContent.trim()==='지수 제외', bc.textContent);
ok('bm 행 사라짐', d.querySelectorAll('#tbl tr.sum.bm').length===0);
clk(bc);
ok('bm 행 복귀', d.querySelectorAll('#tbl tr.sum.bm').length>0);
const q=d.getElementById('q');
q.value='QYLD'; q.dispatchEvent(new w.Event('input',{bubbles:true}));
ok('검색 축소', d.querySelectorAll('#tbl tr.sum').length<N0);
q.value=''; q.dispatchEvent(new w.Event('input',{bubbles:true}));
ok('검색 초기화', d.querySelectorAll('#tbl tr.sum').length===N0);

console.log('── 방법론 ──');
const dc=d.getElementById('disc-meth');
ok('#disc-meth 존재', !!dc);
ok('가중치 바 5개', dc.querySelectorAll('.wrow').length===5, dc.querySelectorAll('.wrow').length);
ok('설명 박스 3개', dc.querySelectorAll('.mbox').length===3, dc.querySelectorAll('.mbox').length);
ok('기본 접힘', !dc.hasAttribute('open'));

console.log('── 분석 차트 ──');
['c1','c2','c3','c4'].forEach(id=>ok('차트 '+id, !!charts[id]));
ok('c1 quad 플러그인', (charts.c1.plugins||[]).some(p=>p&&/^quad/.test(p.id||'')), JSON.stringify((charts.c1.plugins||[]).map(p=>p&&p.id)));
ok('c2 quad 플러그인', (charts.c2.plugins||[]).some(p=>p&&/^quad/.test(p.id||'')));
ok('quad = beforeDatasetsDraw', typeof charts.c1.plugins[0].beforeDatasetsDraw==='function');
ok('c1 데이터셋 5개', charts.c1.data.datasets.length===5, charts.c1.data.datasets.length);
ok('c3 가로 막대', charts.c3.options.indexAxis==='y');
ok('c4 4계열', charts.c4.data.datasets.length===4);
ok('#n1 상관계수', /r = -?\d\.\d\d/.test(d.getElementById('n1').textContent), d.getElementById('n1').textContent.slice(0,50));
ok('#insights 5+', d.querySelectorAll('#insights .ins').length>=5, d.querySelectorAll('#insights .ins').length);
ok('.ins 제목/본문', [...d.querySelectorAll('#insights .ins')].every(e=>!!e.querySelector('.h')&&!!e.querySelector('.b')));
let qe=null;
try{ charts.c1.plugins[0].beforeDatasetsDraw({ctx:CTX,chartArea:{left:10,right:300,top:10,bottom:200},
  scales:{x:{getPixelForValue:()=>150},y:{getPixelForValue:()=>100}}}); }catch(e){ qe=e; }
ok('quad draw 통과', !qe, qe&&qe.message);

console.log('── 테마 ──');
clk(d.getElementById('thbtn'));
ok('라이트 전환', d.documentElement.getAttribute('data-theme')==='light');
ok('라벨 갱신', d.getElementById('thlb').textContent.includes('다크'), d.getElementById('thlb').textContent);
ok('localStorage', w.localStorage.getItem('ccl_theme_v1')==='light');
ok('차트 재생성', !!charts.c1&&!!charts.c4);
ok('표 유지', d.querySelectorAll('#tbl tr.sum').length===N0);
clk(d.getElementById('thbtn'));
ok('다크 복귀', d.documentElement.getAttribute('data-theme')!=='light');

console.log('── 포트폴리오 ──');
clk(d.querySelector('.nav button[data-tab="portfolio"]'));
ok('포트폴리오 활성', d.getElementById('pane-portfolio').classList.contains('on'));
ok('리서치 비활성', !d.getElementById('pane-research').classList.contains('on'));
ok('탭 localStorage', w.localStorage.getItem('ccl_tab_v1')==='portfolio');
ok('빈 상태 안내', d.getElementById('pfempty').style.display!=='none');
ok('빈 상태 경보 숨김', d.getElementById('alertbar').hidden===true);
ok('빈 상태 pfbadge 비움', d.getElementById('pfbadge').textContent==='');
ok('빈 상태 현금섹션 숨김', d.getElementById('pfcash').style.display==='none');

console.log('── 드롭다운 ──');
const A=d.getElementById('ddadd'), AM=d.getElementById('ddaddm');
const M=d.getElementById('ddmore'), MM=d.getElementById('ddmorem');
ok('추가메뉴 기본 닫힘', AM.hidden===true);
clk(A); ok('추가메뉴 열림', AM.hidden===false);
clk(M); ok('배타적 개폐', AM.hidden===true&&MM.hidden===false);
clk(d.body); ok('바깥 클릭 닫힘', AM.hidden===true&&MM.hidden===true);
['pfadd','pfaddbm','pfaddbd','pfaddcm','pfaddlv','pfexp','pfimp','pfclr']
  .forEach(id=>ok('#'+id+' 존재', !!d.getElementById(id)));

console.log('── 보유 추가 ──');
clk(d.getElementById('pfadd')); clk(d.getElementById('pfaddbm')); clk(d.getElementById('pfaddbd'));
const rows=[...d.querySelectorAll('#pftbl tbody tr')];
ok('보유 3행', rows.length===3, rows.length);
ok('#pfbadge = 3종', d.getElementById('pfbadge').textContent==='3종', d.getElementById('pfbadge').textContent);
ok('빈 상태 숨김', d.getElementById('pfempty').style.display==='none');
ok('현금섹션 노출', d.getElementById('pfcash').style.display!=='none');
ok('#pfkpi 채워짐', d.getElementById('pfkpi').children.length>0);
ok('삭제 = .xbtn', rows.every(t=>!!t.querySelector('.xbtn')));
ok('보유 localStorage', !!w.localStorage.getItem('ccl_portfolio_v1'));
const qy=d.querySelector('#pftbl tbody input[data-f="qty"]');
ok('수량 입력칸', !!qy);
qy.value='100'; qy.dispatchEvent(new w.Event('change',{bubbles:true}));
ok('수량 반영 후 3행', d.querySelectorAll('#pftbl tbody tr').length===3);
ok('#pfkpi 갱신', d.getElementById('pfkpi').textContent.trim().length>0);

console.log('── 분배금 추세 ──');
const DS=d.getElementById('dvsum');
ok('#dvsum 3칸', DS.querySelectorAll(':scope > div').length===3, DS.querySelectorAll(':scope > div').length);
ok('라벨 3 · 값 2 · 판정묶음 1',
  DS.querySelectorAll('.l').length===3 && DS.querySelectorAll('.v').length===2 && DS.querySelectorAll('.dvflags').length===1,
  'l='+DS.querySelectorAll('.l').length+' v='+DS.querySelectorAll('.v').length);
ok('첫 칸 전년대비', /([+\-−]?\d+\.\d%)|–/.test(DS.querySelector('.v').textContent), DS.querySelector('.v').textContent.trim());
ok('.dvflags 3배지', DS.querySelectorAll('.dvflags .vd').length===3, DS.querySelectorAll('.dvflags .vd').length);
ok('판정 클래스 유효', [...DS.querySelectorAll('.dvflags .vd')].every(e=>['up','flat','down','ero','na'].some(c=>e.classList.contains(c))));
ok('#dvtbl 3행', d.querySelectorAll('#dvtbl tbody tr').length===3);
ok('#dvtbl 6열', [...d.querySelectorAll('#dvtbl tbody tr')].every(t=>t.children.length===6));
ok('경보 hidden 제어', typeof d.getElementById('alertbar').hidden==='boolean');
ok('#mnlist 렌더', d.getElementById('mnlist').children.length>0);
ok('.mnrow 사용', d.querySelectorAll('#mnlist .mnrow').length>0||!!d.querySelector('#mnlist .mnempty'));
ok('#mnsum 요약', d.getElementById('mnsum').textContent.trim().length>0);

console.log('── 포트폴리오 차트 ──');
['cp1','cp2','cp3','cp4'].forEach(id=>ok('차트 '+id, !!charts[id]));
ok('cp3 도넛', charts.cp3.config.type==='doughnut');
ok('cp3 ctr 플러그인', (charts.cp3.plugins||[]).some(p=>p&&p.id==='ctr'));
ok('cp4 bl100 플러그인', (charts.cp4.plugins||[]).some(p=>p&&p.id==='bl100'), JSON.stringify((charts.cp4.plugins||[]).map(p=>p&&p.id)));
ok('cp4 기준선 데이터셋 제거', !charts.cp4.data.datasets.some(x=>/기준선/.test(x.label||'')));
let be=null;
try{ charts.cp4.plugins.find(p=>p.id==='bl100').afterDatasetsDraw({ctx:CTX,
  chartArea:{left:10,right:300,top:10,bottom:200},scales:{y:{getPixelForValue:()=>100}}}); }catch(e){ be=e; }
ok('bl100 draw 통과', !be, be&&be.message);

console.log('── 세그먼트 ──');
const dv=d.querySelectorAll('#dvseg button');
ok('#dvseg 2버튼', dv.length===2);
clk(dv[1]); ok('월별 모드 판정표 숨김', d.getElementById('dvwrap').style.display==='none');
clk(dv[0]); ok('주당 모드 판정표 노출', d.getElementById('dvwrap').style.display!=='none');
const ax=[...d.querySelectorAll('#axseg button')];
ok('#axseg 3버튼', ax.length===3, ax.length);
clk(ax[2]); ok('축 전환 후 cp1 유지', !!charts.cp1);
clk(ax[0]);

console.log('── 계좌 유형 ──');
const isa=d.querySelector('.chip.acct[data-a="isa"]');
clk(isa);
ok('ISA 활성', isa.classList.contains('on'));
ok('일반 비활성', !d.querySelector('.chip.acct[data-a="general"]').classList.contains('on'));
ok('판정표 유지', d.querySelectorAll('#dvtbl tbody tr').length===3);
ok('#dvsum 세후 라벨', /세후/.test(DS.textContent));

console.log('── 삭제 ──');
clk(d.querySelector('#pftbl tbody .xbtn'));
ok('1행 삭제', d.querySelectorAll('#pftbl tbody tr').length===2);
ok('#pfbadge = 2종', d.getElementById('pfbadge').textContent==='2종');

console.log('── 레거시 잔재 ──');
['dd','nmm','amt'].forEach(c=>ok('.'+c+' 미사용(#mnlist)', !d.querySelector('#mnlist .'+c)));
ok('구 16열 헤더 없음', !d.querySelector('#tbl thead th[data-k="capture_1y"]'));
ok('구 tag 배지 없음(리서치)', !d.querySelector('#tbl tbody .tag'));

console.log('── CSS 토큰 정합 ──');
(function(){
  const css=fs.readFileSync(P,'utf8');
  const blk=(sel)=>{ const i=css.indexOf(sel); const o=css.indexOf('{',i), c=css.indexOf('}',o);
    return new Set([...css.slice(o,c).matchAll(/--([a-z0-9]+)\s*:/g)].map(m=>m[1])); };
  const dark=blk(':root, html[data-theme="dark"]'), light=blk('html[data-theme="light"]');
  const RADII=new Set(['r','r2','r3']);
  const missing=[...dark].filter(k=>!light.has(k)&&!RADII.has(k));
  ok('라이트 테마에 누락 토큰 없음', missing.length===0, missing.join(','));
  ok('라이트 전용 잉여 토큰 없음', [...light].filter(k=>!dark.has(k)).length===0);
  /* applyChartTheme 이 읽는 토큰은 반드시 두 테마 모두에 있어야 한다 */
  ['grid','pfline','surface','tx','tx2','tx3','line','line2','wash','negwash']
    .forEach(k=>ok('토큰 --'+k+' 양쪽 정의', dark.has(k)&&light.has(k)));
})();

console.log('\n'+'='.repeat(44));
console.log('  통과 '+pass+' · 실패 '+fail+' · 총 '+(pass+fail));
console.log('='.repeat(44));
process.exit(fail?1:0);

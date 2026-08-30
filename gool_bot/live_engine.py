"""Flashscore live statistics + goal pressure engine."""
from __future__ import annotations
import json,logging,os,re,time
from dataclasses import dataclass,asdict
from pathlib import Path
import requests
logger=logging.getLogger("live_engine")
FSIGN=os.getenv("FLASHSCORE_FSIGN","SW9D1eZo");FEED_HOSTS=("global","2","46");UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36";STATE_FILE=Path(os.getenv("LIVE_STATE_FILE","live_state.json"))
STAT_MAP={"432":"xg","499":"xgot","12":"possession","34":"shots","13":"shots_on_target","14":"shots_off_target","158":"blocked_shots","461":"shots_inside_box","463":"shots_outside_box","459":"big_chances","16":"corners","471":"touches_box","23":"yellow_cards"}
@dataclass
class LiveMatch:
 event_id:str;minute:int;home:str;away:str;home_score:int;away_score:int;status:str;league:str="";is_halftime:bool=False
@dataclass
class StatsSnapshot:
 ts:int;minute:int;values:dict[str,tuple[float,float]]
@dataclass
class GoalPressureResult:
 score:float;momentum:float;quality:float;context:float;reasons:list[str]
def _to_number(v):
 try:return float(str(v).strip().replace("%",""))
 except ValueError:return 0.
def _feed(path:str)->str:
 headers={"User-Agent":UA,"x-fsign":FSIGN,"Origin":"https://www.flashscore.com","Referer":"https://www.flashscore.com/","Accept":"*/*","Cache-Control":"no-cache"}
 for host in FEED_HOSTS:
  try:
   r=requests.get(f"https://{host}.flashscore.ninja/2/x/feed/{path}",headers=headers,timeout=12)
   if r.status_code==200 and r.text.strip() and not r.text.lstrip().lower().startswith("<"):return r.text
  except requests.RequestException:pass
 return ""
def fetch_stats(event_id):return _feed(f"df_st_1_{event_id}")
def fetch_summary(event_id):return _feed(f"df_sui_1_{event_id}")
def parse_goal_timeline(body:str)->list[str]:
 goals=[];last=(0,0)
 for chunk in (body or "").split("~III"):
  if not chunk:continue
  mm=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})(?:'|\\')?",chunk);hm=re.search(r"INX(?:÷|¬)(\d+)",chunk);am=re.search(r"IOX(?:÷|¬)(\d+)",chunk)
  if not mm or (not hm and not am):continue
  h=int(hm.group(1)) if hm else last[0];a=int(am.group(1)) if am else last[1]
  if h>last[0] or a>last[1]:goals.append(f"{mm.group(1)}' {'хозяева' if h>last[0] else 'гости'}");last=(h,a)
 return goals
def parse_stats(body):
 out={}
 for chunk in (body or "").split("~"):
  m=re.search(r"SD(?:÷|¬)(\d+).*?SH(?:÷|¬)([^¬~]+).*?SI(?:÷|¬)([^¬~]+)",chunk)
  if m:
   sid,h,a=m.groups();name=STAT_MAP.get(sid)
   if name:out[name]=(_to_number(h),_to_number(a))
 return out
def load_state():
 if not STATE_FILE.exists():return {}
 try:return json.loads(STATE_FILE.read_text(encoding="utf-8"))
 except Exception:return {}
def save_snapshot(event_id,snapshot):
 state=load_state();rows=state.setdefault(event_id,[]);rows.append(asdict(snapshot));cutoff=int(time.time())-7200;state[event_id]=[r for r in rows if int(r.get("ts",0))>=cutoff][-30:];STATE_FILE.write_text(json.dumps(state,ensure_ascii=False),encoding="utf-8")
def _delta(values,prev,key):
 a=values.get(key,(0.,0.));b=prev.get(key,(0.,0.));return max(0.,(a[0]+a[1])-(b[0]+b[1]))
def calculate_goal_pressure(match,values,previous=None):
 previous=previous or {};xg=sum(values.get("xg",(0,0)));shots=sum(values.get("shots",(0,0)));sot=sum(values.get("shots_on_target",(0,0)));big=sum(values.get("big_chances",(0,0)));inside=sum(values.get("shots_inside_box",(0,0)));touches=sum(values.get("touches_box",(0,0)));corners=sum(values.get("corners",(0,0)));quality=min(100.,xg*24+sot*5+big*10+inside*1.7+touches*.45);dxg=_delta(values,previous,"xg");dshots=_delta(values,previous,"shots");dsot=_delta(values,previous,"shots_on_target");dbig=_delta(values,previous,"big_chances");dinside=_delta(values,previous,"shots_inside_box");dtouches=_delta(values,previous,"touches_box");dcorners=_delta(values,previous,"corners");momentum=min(100.,dxg*42+dshots*7+dsot*13+dbig*18+dinside*4+dtouches*1.4+dcorners*5);goals=match.home_score+match.away_score;context=65. if match.minute<=45 and goals<=1 else 45. if match.minute<=45 else 75. if match.minute<=75 and goals<=2 else 55. if match.minute<=75 else 70. if goals<=3 else 45.;activity=min(100.,shots*2.2+sot*5.5+corners*1.8);score=min(100.,quality*.38+momentum*.37+activity*.15+context*.10);reasons=[]
 if dxg>=.35:reasons.append(f"xG +{dxg:.2f} за последнее окно")
 if dsot>=2:reasons.append(f"+{int(dsot)} удара в створ")
 if dshots>=4:reasons.append(f"+{int(dshots)} ударов")
 if dbig>=1:reasons.append("появился большой момент")
 if dtouches>=8:reasons.append(f"+{int(dtouches)} касаний в штрафной")
 if not reasons and score>=70:reasons.append("высокое суммарное давление")
 return GoalPressureResult(round(score,1),round(momentum,1),round(quality,1),round(context,1),reasons)

async def discover_live_matches():
 """Full-world master-feed discovery.

Flashscore currently exposes overlapping football master feeds.  The old GOOL
runner only read f_1_0_0_en_1; on some rotations that feed is only a subset of
all LIVE football.  Monkey's validated collector uses f_1_0_3_en_1 and sees the
larger pool.  Read both and union by Flashscore event id so a partial feed cannot
silently hide matches from FT/1H/2H analysis.
 """
 from feed_live_discovery import parse_master_live
 paths=("f_1_0_3_en_1","f_1_0_0_en_1")
 merged={};seen_any=False
 for path in paths:
  body=_feed(path)
  if not body:
   logger.warning("MASTER_FEED_SOURCE path=%s unavailable",path);continue
  seen_any=True
  parsed=parse_master_live(body)
  logger.info("MASTER_FEED_SOURCE path=%s bytes=%d live=%d",path,len(body.encode("utf-8",errors="ignore")),len(parsed))
  for m in parsed:merged[str(m.event_id)]=m
 matches=list(merged.values())
 matches.sort(key=lambda m:(int(getattr(m,"minute",0) or 0),str(getattr(m,"league","") or ""),str(getattr(m,"home","") or "")))
 if not seen_any:logger.warning("Flashscore master feeds unavailable; no browser fallback")
 logger.info("MASTER_FEED_UNION live=%d sources=%d",len(matches),len(paths))
 return matches

def get_previous_values(event_id,current_minute,lookback_minutes=8):
 state=load_state().get(event_id,[]);target=current_minute-lookback_minutes;c=[r for r in state if int(r.get("minute",999))<=target]
 if not c:return None
 return {k:tuple(v) for k,v in c[-1].get("values",{}).items()}

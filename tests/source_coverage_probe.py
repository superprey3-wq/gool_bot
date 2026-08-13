import asyncio, re, unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
import requests
import esd
from live_engine import discover_live_matches

def norm(s):
    s=unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(fc|afc|cf|sc|fk|sv|ac|as|club)\b',' ',s)
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())

def sim(a,b):
    a,b=norm(a),norm(b)
    if not a or not b:return 0.0
    if a==b:return 1.0
    if a in b or b in a:return .92
    return SequenceMatcher(None,a,b).ratio()

def best(home,away,rows,names):
    out=None
    for row in rows:
        h,a=names(row)
        score=max((sim(home,h)+sim(away,a))/2,(sim(home,a)+sim(away,h))/2)
        if out is None or score>out[0]:out=(score,row,h,a)
    return out if out and out[0]>=.72 else None

def has_token(obj,tokens):
    text=str(obj).lower()
    return any(t in text for t in tokens)

async def main():
    live=await discover_live_matches()
    print('FLASH_LIVE',len(live))
    date=datetime.now(timezone.utc).strftime('%Y-%m-%d')

    fm=[]
    try:
        r=requests.get(f'https://football-live-api.vercel.app/api/fotmob/matches/date/{date}',timeout=25)
        print('FOTMOB_HTTP',r.status_code)
        for lg in ((r.json().get('data') or {}).get('leagues') or []):
            for m in lg.get('matches') or []:
                st=m.get('status') or {}
                if st.get('started') and not st.get('finished'):fm.append(m)
    except Exception as e:print('FOTMOB_FATAL',repr(e))
    print('FOTMOB_LIVE',len(fm))

    f_found=f_detail=f_xg=f_shot=f_mom=0
    for m in live:
        hit=best(m.home,m.away,fm,lambda x:((x.get('home') or {}).get('name',''),(x.get('away') or {}).get('name','')))
        if not hit:continue
        f_found+=1; mid=hit[1].get('id')
        try:
            d=requests.get(f'https://football-live-api.vercel.app/api/fotmob/match/{mid}',timeout=20).json().get('data') or {}
            c=d.get('content') or {}; f_detail+=1
            stats=c.get('stats') or {}; shots=((c.get('shotmap') or {}).get('shots') or []); mom=(((c.get('momentum') or {}).get('main') or {}).get('data') or [])
            if has_token(stats,['expected goals','xg']):f_xg+=1
            if shots:f_shot+=1
            if mom:f_mom+=1
            print('FOTMOB_MATCH',m.home,'--',m.away,'sim',round(hit[0],2),'shotmap',len(shots),'momentum',len(mom),'xg',has_token(stats,['expected goals','xg']))
        except Exception as e:print('FOTMOB_DETAIL_ERR',m.home,repr(e))

    try:
        sc=esd.SofascoreClient(); sev=sc.get_events(live=True)
    except Exception as e:
        print('SOFA_FATAL',repr(e)); sev=[]; sc=None
    print('SOFA_LIVE',len(sev))
    s_found=s_stats=s_xg=0
    for m in live:
        hit=best(m.home,m.away,sev,lambda x:(x.home_team.name,x.away_team.name))
        if not hit:continue
        s_found+=1; ev=hit[1]
        try:
            details=sc.get_match_stats(ev.id); s_stats+=1
            if has_token(details,['expected_goals','expected goals','xg']):s_xg+=1
            sog=details.all.shots.shots_on_goal
            print('SOFA_MATCH',m.home,'--',m.away,'sim',round(hit[0],2),'min',ev.current_elapsed_minutes,'score',ev.home_score.current,ev.away_score.current,'sot',sog.home_value,sog.away_value,'xg',has_token(details,['expected_goals','expected goals','xg']))
        except Exception as e:print('SOFA_STATS_ERR',m.home,repr(e))

    total=max(1,len(live))
    print('SUMMARY flash',len(live))
    print('SUMMARY fotmob',f_found,round(100*f_found/total,1),'detail',f_detail,'xg',f_xg,'shotmap',f_shot,'momentum',f_mom)
    print('SUMMARY sofa',s_found,round(100*s_found/total,1),'stats',s_stats,'xg',s_xg)

if __name__=='__main__':asyncio.run(main())

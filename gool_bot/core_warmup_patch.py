"""Safety rules for CORE: warm-up windows and universal 5-minute goal reset."""
import live_candidate_patch as lc
_orig=lc._evaluate
lc.POST_GOAL_SETTLE_MINUTES=5

def _last_goal(goals):
 vals=[]
 for x in goals or []:
  try:vals.append(int(str(x).split("'",1)[0].split("+",1)[0]))
  except:pass
 return max(vals) if vals else None

def _evaluate(m,s,p,goals,market):
 result=_orig(m,s,p,goals,market);minute=int(getattr(m,"minute",0) or 0)
 # First 10 minutes and first 10 minutes after the break are observation only.
 blocked=minute<10 or (46<=minute<55) or bool(getattr(m,"is_halftime",False))
 last=_last_goal(goals)
 if last is not None and minute-last<5:blocked=True
 if not blocked:return result
 qualifies,route,master,sc,hz,mkt=result
 return False,"WARMUP_OR_POST_GOAL",master,sc,hz,mkt
lc._evaluate=_evaluate

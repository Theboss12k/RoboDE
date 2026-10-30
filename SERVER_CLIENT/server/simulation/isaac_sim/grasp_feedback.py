"""Confirm a simulated grasp from measured object-following motion, not closure.

Only native rigid-body and joint observations enter this tracker. It does not
attach, reposition or apply forces to objects.
"""
import math

class ObservedGrasp:
    def __init__(self):self.candidates={}
    def update(self,key,tool,objects,closed,time):
        if not closed:self.candidates.pop(key,None);return None
        nearest=min(objects,key=lambda o:math.dist(tool,o['position']),default=None)
        if nearest is None or math.dist(tool,nearest['position'])>.03:self.candidates.pop(key,None);return None
        candidate=self.candidates.get(key);offset=[a-b for a,b in zip(nearest['position'],tool)]
        if candidate is None or candidate['object_id']!=nearest['id']:
            self.candidates[key]={'object_id':nearest['id'],'object_start':list(nearest['position']),'tool_start':list(tool),'offset':offset,'since':time,'stable':1,'confirmed':False};return None
        if math.dist(offset,candidate['offset'])>.008:self.candidates.pop(key,None);return None
        candidate['stable']+=1
        if candidate['stable']>=3 and time-candidate['since']>=.08 and math.dist(nearest['position'],candidate['object_start'])>=.01 and math.dist(tool,candidate['tool_start'])>=.01:candidate['confirmed']=True
        return candidate['object_id'] if candidate['confirmed'] else None

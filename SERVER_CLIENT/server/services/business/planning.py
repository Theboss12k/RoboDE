"""Business commands compile into the existing atomic-task engine, never a second executor."""
import re
from shared.models.domain import TaskDefinition,Pose
from services.planning.templates import expand_template
from services.world_model.world import placement_satisfied


def normalized(value):
    return re.sub(r'[^a-z0-9]','',value.casefold())


def resolve_name(value,objects,kind=None,aliases=None):
    candidates=[o for o in objects if kind is None or o.kind==kind]
    matches=[o for o in candidates if normalized(value) in {normalized(o.id),normalized(o.name),normalized((aliases or {}).get(o.id,''))}]
    if len(matches)!=1:raise ValueError(f'“{value}” is not a unique available asset. Choose its name from the workspace.')
    return matches[0]


def parse_transfer(text,objects,aliases=None):
    # Fully anchored: negation/conditions/repetition cannot be silently reduced to a transfer.
    text=text.strip().rstrip('.!')
    match=re.fullmatch(r'(?:please\s+)?(?:move|transfer|take)\s+(?:the\s+)?(.+?)\s+(?:from\s+(?:the\s+)?(.+?)\s+)?(?:to|into|in|onto)\s+(?:the\s+)?(.+)',text,re.I)
    if not match:return None
    if re.search(r'\b(not|without|unless|if|then|twice|repeat|and|but|except)\b',text,re.I):return None
    item=resolve_name(match[1],objects,'object',aliases)
    source=resolve_name(match[2],objects,aliases=aliases) if match[2] else None
    destination=resolve_name(match[3],objects,aliases=aliases)
    if destination.kind not in {'region','obstacle'}:raise ValueError('Choose a destination area or support surface.')
    if source and source.id==destination.id:raise ValueError('Source and destination must be different.')
    if source and not placement_satisfied(item,source,'inside' if source.kind=='region' else 'on_surface'):
        raise ValueError(f'{item.name} is not currently at {source.name}. Refresh the workspace and check the source.')
    return item,source,destination


def transfer_tasks(model,instance,objects,item,destination):
    if destination.kind=='region':return expand_template('pick_place',model,instance,objects,item.id,destination.id)
    if any(getattr(item.size,a)>getattr(destination.size,a) for a in ('x','y')):raise ValueError('The item does not fit on the destination surface.')
    # Reuse the tested grasp template at a temporary logical volume, then associate
    # every task with the real surface resource and verify actual support contact.
    z=destination.position.z+destination.size.z/2+item.size.z/2
    virtual=destination.model_copy(update={'kind':'region','position':Pose(x=destination.position.x,y=destination.position.y,z=z),'size':Pose(x=destination.size.x,y=destination.size.y,z=max(.12,item.size.z+.02))})
    tasks=expand_template('pick_place',model,instance,[virtual if o.id==destination.id else o for o in objects],item.id,destination.id)
    for task in tasks:
        task.placement='on_surface'
        if task.id=='lower':task.name='Lower onto '+destination.name
    return [TaskDefinition.model_validate(t.model_dump()) for t in tasks]

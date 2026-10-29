"""Local configured Trailblazer name; observations stay separate from settings.

March7th reference: get_remembrance_trailblazer_name and its strategy callers.
Pinned provenance and GPL license: assets/upstream/March7thAssistant/source.json.
"""
import math

from .currency_wars_match import unit_name
from .models import AutomationError,Scene,Token

PREFIX='currency_name_'
PUBLIC_NAME='记忆开拓者'


def validate_name(value):
    if not isinstance(value,str) or len(value)>40 or any(not c.isprintable() for c in value):
        raise ValueError('记忆开拓者名称须为最多40个可见字符，留空表示不配置。')
    result=unit_name(value.strip())
    if value.strip() and not result:raise ValueError('记忆开拓者名称归一化后不能为空。')
    return result


def resolve_name(settings,explicit=None,session=None,*,resume=False):
    requested=None if explicit is None else validate_name(explicit)
    if resume:
        stored=validate_name((session or {}).get('remembrance_name',''))
        if requested is not None and requested!=stored:
            raise AutomationError('本次记忆开拓者名称与已记录对局不同，未中途改写名称。')
        return stored
    return validate_name(getattr(settings,'currency_remembrance_name','') if requested is None else requested)


def with_name(names,strategy,name=''):
    name=validate_name(name)
    if not name or strategy=='default' or name in names:return tuple(names)
    after=max((i for i,n in enumerate(names) if n in ('瓦尔特','昔涟','刻律德菈')),default=0)+1
    return tuple(names[:after])+(name,)+tuple(names[after:])


def snapshot_name(snapshot):
    names=getattr(snapshot,'private_names',())
    return names[0] if names else ''


def basis_name(data):
    names=data.get('basis',{}).get('snapshot',{}).get('private_names',())
    return names[0] if names else ''


def _groups(scene):
    return {key.rsplit('.',1)[0] for key in scene.field_reads if key.startswith(PREFIX)}


def pending_name(scene,roi):
    return any(t is not None and t.within(roi) for key,values in scene.field_reads.items()
               if key.startswith(PREFIX) and key.endswith('.pending') for t in values)


def configured_name(scene,roi,confidence=.65):
    found=[]
    for key in _groups(scene):
        direct=scene.field_reads.get(key+'.direct',())
        if direct:
            if len(direct)!=1 or direct[0] is None or direct[0] not in scene.tokens:continue
            values=list(direct)
        else:
            a,b=scene.field_reads.get(key+'.raw',()),scene.field_reads.get(key+'.binary',())
            if len(a)!=1 or len(b)!=1:continue
            values=list(a+b)
        if (any(t is None or not t.within(roi) or not math.isfinite(t.score) or not max(.9,confidence)<=t.score<=1 for t in values)
                or len({unit_name(t.text) for t in values})!=1):continue
        name=unit_name(values[0].text)
        if any(t.within(roi) and t.score>=confidence and unit_name(t.text)!=name for t in scene.tokens):continue
        found.append(values[0])
    return found[0] if len(found)==1 else None


def observed_private_names(scene):
    return tuple(sorted({unit_name(t.text) for key,values in scene.field_reads.items() if key.startswith(PREFIX)
                         for t in values if t is not None and t.text}))


def supplement_configured_names(scene,reader,name,confidence=.65):
    name=validate_name(name)
    if not name or scene.image is None:return scene
    import cv2
    from .currency_wars import observe
    kind=observe(scene,confidence).page_kind
    regions=[]
    if kind=='shop':
        regions=[('shop'+str(i),(.192+.14*i,.265,.292+.14*i,.305)) for i in range(5)]
    elif kind=='character':regions=[('owned',(.775,.19,.91,.235))]
    elif kind=='supply_selection':
        from .currency_wars_supply_fields import _items,CENTERS
        try:items=_items(scene,confidence)
        except AutomationError:return scene
        regions=[('supply'+str(i),(x-.09,.50,x+.09,.55)) for i,x in enumerate(CENTERS[len(items)])]
    elif kind in ('hiring_selection','expert_selection'):
        tokens=sorted((t for t in scene.tokens if t.within((.14,.33,.90,.39)) and unit_name(t.text)==name),key=lambda t:t.center[0])
        regions=[('reward'+str(i),t.box) for i,t in enumerate(tokens[:5])]
    fields=dict(scene.field_reads);h,w=scene.image.shape[:2]
    for scope,roi in regions:
        raw=[t for t in scene.tokens if t.within(roi) and confidence<=t.score<=1]
        matches=[t for t in raw if unit_name(t.text)==name];key=PREFIX+scope
        if len(matches)==1:
            fields[key+'.pending']=(matches[0],)
            if matches[0].score>=max(.9,confidence) and len(raw)==1:
                fields[key+'.direct']=(matches[0],);continue
        elif raw:continue
        if not hasattr(reader,'read_configured_unit_name'):continue
        x1,y1,x2,y2=roi;patch=scene.image[round(y1*h):round(y2*h),round(x1*w):round(x2*w)]
        binary=cv2.threshold(cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY),160,255,cv2.THRESH_BINARY)[1]
        for mode,sample in zip(('raw','binary'),(patch,binary)):
            t=reader.read_configured_unit_name(sample,name)
            fields[key+'.'+mode]=(Token(t.text,t.score,roi) if t is not None and unit_name(t.text)==name else None,)
    return Scene(scene.tokens,scene.image,scene.geometry,scene.captured_at,fields)

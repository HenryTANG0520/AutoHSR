"""Observed record-window statistics, distinct from real lifetime/pity history.

References March7thAssistant WarpExport.data_to_html, pinned 7cf6c6b.
UIDs and five-star names in analyze() are local UI data, never model payloads.
"""
from copy import deepcopy
from .warp_records import POOLS,merge

POOL_NAMES={'1':'常驻跃迁','2':'始发跃迁','11':'角色活动跃迁','12':'光锥活动跃迁',
            '21':'角色联动跃迁','22':'光锥联动跃迁'}


def positions(rows):
    """Annotate validated, numerically ordered records without inventing ranks."""
    counters={p:dict(index=0,span=0,seen_five=False,certain=True) for p in POOLS}
    for index,row in enumerate(rows,1):
        state=counters[row['gacha_type']];state['index']+=1;state['span']+=1
        rank=row.get('rank_type')
        if rank is None:state['certain']=False
        distance=state['span'] if state['seen_five'] and state['certain'] else None
        yield row,dict(index=index,pool_index=state['index'],span_records=state['span'],
                       since_previous_five_records=distance,
                       scope='observed' if distance is not None else 'unknown_rank' if not state['certain'] else 'window_prefix')
        if rank=='5':state.update(span=0,seen_five=True,certain=True)


def analyze(accounts,*,history=True,cancel=None):
    """Per account/pool; even bounded observed intervals can contain data gaps."""
    from .warp_fetch import checkpoint
    checkpoint(cancel)
    result=[]
    for ordinal,value in enumerate(merge(accounts),1):
        checkpoint(cancel)
        pools={p:dict(records=0,rank_counts={r:0 for r in ('3','4','5','unknown')},
            item_quantity_sum=0,observed_tail_records=0,known_tail_records=None,
            bounded_intervals=0,bounded_interval_sum=0,mean_bounded_interval_records=None,
            time_order_consistent=True,first_time=None,last_time=None,range_start=None,range_end=None)
            for p in POOLS}
        if history:
            for pool in pools.values():pool['five_star_history']=[]
        for row,position in positions(value['list']):
            if position['index']%256==1:checkpoint(cancel)
            pool=pools[row['gacha_type']];rank=row.get('rank_type','unknown');pool['records']+=1
            pool['rank_counts'][rank]+=1
            if 'count' not in row:pool['item_quantity_sum']=None
            elif pool['item_quantity_sum'] is not None:pool['item_quantity_sum']+=int(row['count'])
            timestamp=row['time']
            if pool['last_time'] is not None and timestamp<pool['last_time']:pool['time_order_consistent']=False
            if pool['first_time'] is None:pool['first_time']=timestamp
            pool['last_time']=timestamp
            pool['range_start']=min(pool['range_start'],timestamp) if pool['range_start'] else timestamp
            pool['range_end']=max(pool['range_end'],timestamp) if pool['range_end'] else timestamp
            distance=position['since_previous_five_records']
            if rank=='5':
                if distance is not None:
                    pool['bounded_intervals']+=1;pool['bounded_interval_sum']+=distance
                if history:pool['five_star_history'].append(dict(id=row['id'],name=row.get('name'),time=timestamp,
                    observed_span_records=position['span_records'],bounded_interval_records=distance,
                    scope=position['scope']))
                pool['observed_tail_records']=0;pool['known_tail_records']=0
            else:
                pool['observed_tail_records']=position['span_records'];pool['known_tail_records']=distance
        for pool in pools.values():
            pool['rank_shares']={rank:count/pool['records'] if pool['records'] else None
                                 for rank,count in pool['rank_counts'].items()}
            intervals=pool['bounded_intervals']
            if intervals:pool['mean_bounded_interval_records']=pool['bounded_interval_sum']/intervals
            pool.pop('bounded_interval_sum')
        result.append(dict(uid=value['uid'],timezone=value['timezone'],lang=value.get('lang'),index=ordinal,pools=pools))
    checkpoint(cancel)
    return dict(scope='imported_record_window',history_complete=False,accounts=result)


def public_statistics(analysis):
    """Explicit allowlist: no UID, names, record IDs, dates or paths in events."""
    fields=('records','rank_counts','rank_shares','item_quantity_sum','observed_tail_records','known_tail_records',
            'bounded_intervals','mean_bounded_interval_records','time_order_consistent')
    return dict(scope='imported_record_window',history_complete=False,accounts=[dict(index=a['index'],
        pools={p:{key:deepcopy(value[key]) for key in fields} for p,value in a['pools'].items()}) for a in analysis['accounts']])

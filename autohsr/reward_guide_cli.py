"""Offline reward guide PNG export."""

import json


def run(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (len(flags) != 2 or set(flags) != {'--reward-guide-stitch', '--reward-guide-output'}
            or args.reward_guide_stitch is None or args.reward_guide_output is None):
        parser.error('请只指定 --reward-guide-stitch PNG … 和 --reward-guide-output NEW_PNG。')

    from .reward_guide_export import export_reward_guide

    receipt = export_reward_guide(args.reward_guide_stitch, args.reward_guide_output)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt['status'] == 'ok' else 1

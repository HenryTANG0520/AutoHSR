"""Observed match HUD and conservative transaction feedback, without inputs."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .currency_wars_pages import classify_page,is_bench_full_notice
from .models import Scene, Token, normalize


@dataclass(frozen=True)
class Offer:
    slot: int
    name: str
    cost: int | None


@dataclass(frozen=True)
class MatchState:
    page: str
    node: str | None = None
    gold: int | None = None
    level: int | None = None
    experience: tuple[int, int] | None = None
    deployment: tuple[int, int] | None = None
    hp: int | None = None
    offers: tuple[Offer, ...] = ()
    probabilities: tuple[int, ...] | None = None


def _unique(tokens, roi, pattern, convert):
    values = set()
    for token in tokens:
        if token.within(roi) and (match := re.fullmatch(pattern, normalize(token.text))):
            values.add(convert(match))
    return next(iter(values)) if len(values) == 1 else None


def read_match(scene: Scene, confidence=.65) -> MatchState | None:
    tokens = [t for t in scene.tokens if math.isfinite(t.score) and confidence <= t.score <= 1
              and len(t.box) == 4 and all(math.isfinite(x) and 0 <= x <= 1 for x in t.box)
              and t.box[0] < t.box[2] and t.box[1] < t.box[3]]
    page = classify_page(tokens)
    if page not in ("preparation", "shop", "character", "bench_full"):
        return None
    if page=='bench_full' and classify_page([t for t in tokens if not is_bench_full_notice(t)])!='preparation':
        return None
    number = lambda roi: _unique(tokens, roi, r"[0-9]{1,4}", lambda m: int(m[0]))
    level = _unique(tokens, (.125, .815, .185, .87), r"lv\.?([1-9]|1[0-9])", lambda m: int(m[1]))
    experience = _unique(tokens, (.13, .865, .18, .9), r"([0-9]{1,3})/([0-9]{1,3})",
                         lambda m: (int(m[1]), int(m[2])))
    deployment = _unique(tokens, (.43, .18, .55, .36), r"[iIl|]?([0-9]{1,2})/([0-9]{1,2})",
                         lambda m: (int(m[1]), int(m[2]))) if page != "shop" else None
    if deployment and not 0 <= deployment[0] <= deployment[1] <= 20:
        deployment = None
    if experience and not 0 <= experience[0] < experience[1]:
        experience = None
    node = _unique(tokens, (.1, .04, .29, .13), r"([1-3])-([1-9][0-9]?)", lambda m: m[0])
    offers, probabilities = [], None
    if page == "shop":
        for slot in range(5):
            left = .192 + .14 * slot
            name = _unique(tokens, (left, .265, left + .115, .305), r"[\u4e00-\u9fff·]{2,16}", lambda m: m[0])
            cost = number((left + .109, .265, left + .125, .305))
            if name:
                offers.append(Offer(slot, name, cost if cost in (1, 2, 3, 4, 5) else None))
        probs = [_unique(tokens, (left, .33, right, .39), r"[■□]?([0-9]{1,3})%", lambda m: int(m[1]))
                 for left, right in ((.49, .55), (.55, .6), (.6, .65), (.65, .69), (.7, .74))]
        if None not in probs and sum(probs) == 100:
            probabilities = tuple(probs)
    hp = number((.735, .05, .78, .095)) if page != "shop" else None
    # Sky can capture an occluding desktop toast. Its text must not become gold.
    gold_blocked = page == "character" or any(t.within((.84, .83, 1, .95))
        and not re.fullmatch(r"[0-9]{1,4}|商店|收起", normalize(t.text)) for t in tokens)
    return MatchState(page, node, None if gold_blocked else number((.851, .829, .87, .868)), level, experience,
                      deployment, hp if hp is not None and hp <= 100 else None,
                      tuple(offers), probabilities)


def supplement_numbers(scene: Scene, reader) -> Scene:
    """OCR small HUD numbers at native detail, keeping original pixels/evidence.

    Full-screen OCR downsizes to 1920px and often misses single digits beside
    currency icons. Only numbers wholly inside calibrated fields are added.
    Obscured fields remain unknown; no value is inferred from button color.
    """
    import cv2
    page = classify_page(scene.tokens)
    if scene.image is None or page not in ("preparation", "shop", "character", "bench_full", "battle", "node_result", "final_victory", "expert_selection"):
        return scene
    rois = [(.843, .825, .876, .875), (.132, .815, .181, .866)]
    if page=='preparation':
        rois.append((.153,.908,.174,.933))
    if page == "shop":
        rois += [(.301 + .14 * slot, .263, .317 + .14 * slot, .304) for slot in range(5)]
    height, width = scene.image.shape[:2]
    tokens = list(scene.tokens)
    if page=='expert_selection':
        roi=(.828,.25,.849,.292)
        x1,y1,x2,y2=roi
        patch=cv2.resize(scene.image[round(y1*height):round(y2*height),round(x1*width):round(x2*width)],None,fx=3,fy=3)
        parts=reader.read(patch).tokens
        if not parts and hasattr(reader,'read_number'):
            token=reader.read_number(patch)
            parts=[token] if token is not None else []
        for t in parts:
            if re.fullmatch(r'[0-9]{1,2}',normalize(t.text)):
                tokens.append(Token(t.text,t.score,roi))
        return Scene(tokens,scene.image,scene.geometry,scene.captured_at)
    if page in ('node_result','final_victory'):
        # The adjacent crossed-swords icon can join OCR as "X战斗". Read
        # only the bounded node field, without deleting arbitrary letters.
        # Short reward nodes center a compact badge farther right than longer
        # combat/boss labels. Both crops exclude their adjacent type icons.
        for roi in ((.405,.245,.438,.286),(.462,.245,.485,.286)):
            x1,y1,x2,y2=roi
            patch=cv2.resize(scene.image[round(y1*height):round(y2*height),round(x1*width):round(x2*width)],None,fx=3,fy=3)
            parts=reader.read(patch).tokens
            if not any(re.fullmatch(r'[1-3]-[1-9][0-9]?',normalize(t.text)) for t in parts) and hasattr(reader,'read_node'):
                node=reader.read_node(patch)
                if node is not None:
                    parts.append(node)
            for t in parts:
                if re.fullmatch(r'[1-3]-[1-9][0-9]?',normalize(t.text)):
                    tokens.append(Token(t.text,t.score,roi))
        return Scene(tokens,scene.image,scene.geometry,scene.captured_at)
    if page == 'battle':
        # Reward fights expand the HUD with drop counters and shift the node.
        for x1,y1,x2,y2 in ((.358,0,.39,.045),(.312,0,.342,.045)):
            patch = cv2.resize(scene.image[round(y1*height):round(y2*height),round(x1*width):round(x2*width)],None,fx=3,fy=3)
            for t in reader.read(patch).tokens:
                if re.fullmatch(r'[1-3]-[1-9][0-9]?',normalize(t.text)):
                    tokens.append(Token(t.text,t.score,(x1,y1,x2,y2)))
        return Scene(tokens,scene.image,scene.geometry,scene.captured_at)
    for x1, y1, x2, y2 in rois:
        left, top, right, bottom = round(x1 * width), round(y1 * height), round(x2 * width), round(y2 * height)
        patch = cv2.resize(scene.image[top:bottom, left:right], None, fx=3, fy=3)
        found = reader.read(patch)
        for token in found.tokens:
            if re.fullmatch(r"(?:[0-9]{1,4}|lv\.?[0-9]{1,2}|[iIl|]?[0-9]{1,2}/[0-9]{1,2})", normalize(token.text)):
                box = tuple((left + token.box[i] * (right-left)) / width if i % 2 == 0 else
                            (top + token.box[i] * (bottom-top)) / height for i in range(4))
                tokens.append(Token(token.text, token.score, box))
    current=read_match(Scene(tokens,scene.image,scene.geometry,scene.captured_at),.65)
    if current is not None and current.level is None and hasattr(reader,'read_number'):
        patch=cv2.resize(scene.image[round(.815*height):round(.866*height),round(.154*width):round(.178*width)],None,fx=3,fy=3)
        number=reader.read_number(patch)
        if number is not None and 1<=int(number.text)<=10:
            tokens.append(Token('Lv.'+number.text,number.score,(.154,.815,.178,.866)))
    if page in ('preparation', 'character') and read_match(scene, .65).deployment is None:
        # The slanted slash is often read as "1" (e.g. i616). Read the two
        # numbers independently in their fixed HUD fields; never rewrite an
        # arbitrary three-digit OCR string into a deployment ratio.
        patch = cv2.resize(scene.image[round(.19*height):round(.265*height),round(.46*width):round(.54*width)],None,fx=3,fy=3)
        parts = reader.read(patch).tokens
        counts, scores = [], []
        for roi in ((.04,0,.43,1),(.60,0,.97,1)):
            found = [t for t in parts if t.within(roi) and t.box[0] >= roi[0] and t.box[2] <= roi[2]
                     and t.score >= .65 and re.fullmatch(r'[0-9]{1,2}',normalize(t.text))]
            values = {int(normalize(t.text)) for t in found}
            counts.append(next(iter(values)) if len(values)==1 else None)
            scores.extend(t.score for t in found)
        if None in counts:
            # Separate crops recover a digit omitted by the wide OCR pass;
            # the slash is outside both crops, so i777 is never rewritten.
            counts,scores=[],[]
            for x1,x2 in ((.462,.492),(.510,.538)):
                patch=cv2.resize(scene.image[round(.19*height):round(.265*height),round(x1*width):round(x2*width)],None,fx=3,fy=3)
                parts=reader.read(patch).tokens
                if not parts and hasattr(reader,'read_number'):
                    token=reader.read_number(patch)
                    parts=[token] if token is not None else []
                found=[t for t in parts if .65<=t.score<=1
                       and re.fullmatch(r'[0-9]{1,2}',normalize(t.text))]
                values={int(normalize(t.text)) for t in found}
                counts.append(next(iter(values)) if len(values)==1 else None)
                scores.extend(t.score for t in found)
        if None not in counts and 0 <= counts[0] <= counts[1] <= 20 and counts[1] > 0:
            tokens.append(Token(f'{counts[0]}/{counts[1]}',min(scores),(.46,.19,.54,.265)))
    return Scene(tokens, scene.image, scene.geometry, scene.captured_at)


def verify_purchase(before: MatchState, after: MatchState, offer: Offer) -> str:
    """No automatic retry on ambiguous feedback, even if the offer vanished."""
    if before.page != "shop" or after.page != "shop" or not before.node or before.node != after.node:
        return "unknown"
    if (offer not in before.offers or type(offer.cost) is not int or offer.cost not in (1, 2, 3, 4, 5)
            or type(before.gold) is not int or type(after.gold) is not int or min(before.gold, after.gold) < 0):
        return "unknown"
    if before.gold < offer.cost:
        return "unknown"
    remaining = next((o for o in after.offers if o.slot == offer.slot), None)
    if remaining is None and before.gold - after.gold == offer.cost:
        return "verified"
    if remaining == offer and before.gold == after.gold:
        return "unchanged"
    return "unknown"


def verify_experience(before: MatchState, after: MatchState) -> str:
    if before.page not in ("preparation", "shop") or before.page != after.page or not before.node or before.node != after.node:
        return "unknown"
    if any(v is None for v in (before.gold, after.gold, before.level, after.level, before.experience, after.experience)):
        return "unknown"
    if before.gold - after.gold != 4:
        return "unchanged" if before == after else "unknown"
    gained = (after.experience[0] - before.experience[0] if after.level == before.level else
              before.experience[1] - before.experience[0] + after.experience[0]
              if after.level == before.level + 1 else None)
    return "verified" if gained == 4 else "unknown"

bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G's brains (plus ChatGPT brawn)",
    "version": (3, 0, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A maze generator exploring parsimony, with an option to make a boxed city.",
    "category": "Add Mesh",
}

# ──────────────────────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────────────────────
import bpy, random, math, os, copy, time
from mathutils import Vector
from collections import deque, Counter
from heapq import heappush, heappop
from bpy.props import (IntProperty, FloatProperty, BoolProperty, FloatVectorProperty,
                       PointerProperty, StringProperty, EnumProperty)
from bpy.types import Operator, Panel, PropertyGroup

# ──────────────────────────────────────────────────────────────────────────────
# In-memory cache (scene-keyed + global fallback)
# ──────────────────────────────────────────────────────────────────────────────
MODULE_CACHE = {}
def _default_cache():
    return {
        "bitmap": None, "rows": 0, "cols": 0,
        "start": None, "end": None,
        "off_x": 0.0, "off_y": 0.0, "cell_w": 1.0, "cell_h": 1.0,
        "paths": [],
        "clearance": None, "graph": None,
        "metrics": [], "metrics_summary": {},
        "plaza_cells": set(),
    }
def get_cache(scene, read_only=False):
    k = scene.as_pointer()
    data = MODULE_CACHE.get(k)
    if data is None:
        return _default_cache() if read_only else None
    return data
def set_cache(scene, data):
    """Store cache for this scene and a global fallback copy."""
    key = scene.as_pointer()
    MODULE_CACHE[key] = data
    MODULE_CACHE["__last__"] = data  # fallback for operators called from odd contexts

# ──────────────────────────────────────────────────────────────────────────────
# Small utilities
# ──────────────────────────────────────────────────────────────────────────────
def get_collection(name):
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col

def clear_collection(col, name_prefixes=None):
    for ob in list(col.objects):
        if (name_prefixes is None) or any(ob.name.startswith(p) for p in name_prefixes):
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            bpy.data.objects.remove(ob)

def link_exclusive(ob, target_col):
    if target_col not in ob.users_collection:
        target_col.objects.link(ob)
    for c in list(ob.users_collection):
        if c != target_col:
            c.objects.unlink(ob)

def ensure_mat(name, rgba=(1,1,1,1)):
    m = bpy.data.materials.get(name)
    if not m:
        m = bpy.data.materials.new(name=name)
        m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = rgba
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m

def sit_on_ground(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    o_eval = obj.evaluated_get(dg)
    bb = [o_eval.matrix_world @ Vector(c) for c in o_eval.bound_box]
    min_z = min(v.z for v in bb)
    obj.location.z -= min_z

def rc_to_world(off_x, off_y, cell_w, cell_h, rc):
    r, c = rc
    return off_x + c*cell_w, -(off_y + r*cell_h)

# ──────────────────────────────────────────────────────────────────────────────
# Prim's maze generation (grid with walls=True, streets=False)
# ──────────────────────────────────────────────────────────────────────────────
def prims_maze(rows, cols, rng):
    H, W = rows*2+1, cols*2+1
    g = [[True]*W for _ in range(H)]
    sr, sc = rng.randrange(rows), rng.randrange(cols)
    r, c = sr*2+1, sc*2+1
    g[r][c] = False
    frontier = []
    def push(rr, cc):
        for dr, dc in ((-2,0),(2,0),(0,-2),(0,2)):
            r2, c2 = rr+dr, cc+dc
            if 1 <= r2 < H-1 and 1 <= c2 < W-1 and g[r2][c2]:
                frontier.append(((r2, c2), (rr + dr//2, cc + dc//2)))
    push(r, c)
    while frontier:
        i = rng.randrange(len(frontier))
        (rr, cc), (wr, wc) = frontier.pop(i)
        if g[rr][cc]:
            g[wr][wc] = False
            g[rr][cc] = False
            push(rr, cc)

    # carve single start/end openings on opposite borders
    start = end = None
    for r in range(1, H-1):
        if not g[r][1]:
            g[r][0] = False
            start = (r, 0)
            break
    for r in range(H-2, 0, -1):
        if not g[r][W-2]:
            g[r][W-1] = False
            end = (r, W-1)
            break
    return g, H, W, start, end

def inward(rc, rows, cols):
    r, c = rc
    if r == 0: return (1, c)
    if r == rows-1: return (rows-2, c)
    if c == 0: return (r, 1)
    if c == cols-1: return (r, cols-2)
    return rc

def merge_rectangles(grid, rows, cols):
    g = [row[:] for row in grid]
    blocks = []
    for r in range(rows):
        c = 0
        while c < cols:
            if not g[r][c]:
                c += 1
                continue
            w = 1
            while c+w < cols and g[r][c+w]:
                w += 1
            h = 1
            while r+h < rows and all(g[r+h][cc] for cc in range(c, c+w)):
                h += 1
            for rr in range(r, r+h):
                for cc in range(c, c+w):
                    g[rr][cc] = False
            blocks.append((r, c, h, w))
            c += w
    return blocks

# ──────────────────────────────────────────────────────────────────────────────
# City network tweaks on top of Prim's (loops, cul-de-sacs, plazas)
# ──────────────────────────────────────────────────────────────────────────────
def carve_cross_links(grid, H, W, rng, ratio):
    if ratio <= 0: return
    cand = []
    for r in range(2, H-2):
        for c in range(2, W-2):
            if grid[r][c]:
                # potential cross if adjacent passages are opposite
                if (not grid[r][c-1] and not grid[r][c+1]) or (not grid[r-1][c] and not grid[r+1][c]):
                    cand.append((r, c))
    rng.shuffle(cand)
    opens = int(len(cand) * ratio)
    for (r, c) in cand[:opens]:
        grid[r][c] = False

def carve_culdesacs(grid, H, W, rng, prob, maxlen):
    if prob <= 0: return
    dirs = [(1,0),(-1,0),(0,1),(0,-1)]
    streets = [(r,c) for r in range(1,H-1) for c in range(1,W-1) if not grid[r][c]]
    rng.shuffle(streets)
    for (r,c) in streets:
        if rng.random() > prob: continue
        dr, dc = rng.choice(dirs)
        length = rng.randint(1, maxlen)
        rr, cc = r, c
        for _ in range(length):
            rr, cc = rr+dr, cc+dc
            if not (1 <= rr < H-1 and 1 <= cc < W-1): break
            if not grid[rr][cc]: break
            neigh = sum((not grid[rr+ar][cc+ac]) for (ar,ac) in dirs if 0 <= rr+ar < H and 0 <= cc+ac < W)
            if neigh > 1: break
            grid[rr][cc] = False

def carve_plazas(grid, H, W, rng, prob, base_edge, plaza_out_set):
    if prob <= 0: return
    streets = [(r,c) for r in range(2,H-2) for c in range(2,W-2) if not grid[r][c]]
    rng.shuffle(streets)
    for (r0,c0) in streets:
        if rng.random() > prob: continue
        s = max(2, base_edge + rng.choice([-1,0,1]))
        r = max(1, min(H-1-s, r0 - s//2))
        c = max(1, min(W-1-s, c0 - s//2))
        for rr in range(r, r+s):
            for cc in range(c, c+s):
                if 1 <= rr < H-1 and 1 <= cc < W-1:
                    grid[rr][cc] = False
                    plaza_out_set.add((rr,cc))

def city_network(rows, cols, rng, jitter, loop_ratio, cul_p, cul_len, plaza_p, plaza_edge, plaza_out_set):
    g, H, W, s_open, e_open = prims_maze(rows, cols, rng)
    carve_cross_links(g, H, W, rng, ratio=jitter*0.6 + loop_ratio)
    carve_plazas(g, H, W, rng, prob=plaza_p, base_edge=plaza_edge, plaza_out_set=plaza_out_set)
    carve_culdesacs(g, H, W, rng, prob=cul_p, maxlen=cul_len)
    if s_open and g[s_open[0]][s_open[1]]:
        g[s_open[0]][s_open[1]] = False
    if e_open and g[e_open[0]][e_open[1]]:
        g[e_open[0]][e_open[1]] = False
    start = inward(s_open, H, W)
    end   = inward(e_open,   H, W)
    return g, H, W, start, end

# ──────────────────────────────────────────────────────────────────────────────
# Pathfinding helpers (grid and graph)
# ──────────────────────────────────────────────────────────────────────────────
def neighbors_passages(g, r, c):
    R, C = len(g), len(g[0])
    for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr, cc = r+dr, c+dc
        if 0 <= rr < R and 0 <= cc < C and not g[rr][cc]:
            yield rr, cc, dr, dc

def clearance_score(g):
    R, C = len(g), len(g[0])
    s = [[0]*C for _ in range(R)]
    for r in range(R):
        for c in range(C):
            if g[r][c]: continue
            walls = 0
            for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
                rr, cc = r+dr, c+dc
                if 0 <= rr < R and 0 <= cc < C and g[rr][cc]:
                    walls += 1
            s[r][c] = walls
    return s

def manhattan(a, b): return abs(a[0]-b[0]) + abs(a[1]-b[1])

def dijkstra_cost(g, start, goal, params, forbidden=None, clr=None):
    R, C = len(g), len(g[0])
    if clr is None: clr = clearance_score(g)
    forbidden = forbidden or set()
    step = params.get('step',1.0)
    tau  = params.get('turn',0.0)
    alley= params.get('alley',0.0)
    INF = 10**12
    dist = {}
    prev = {}
    pq   = []
    s = (start[0], start[1], (0,0))
    dist[s] = 0.0
    def h(r,c,pi): return manhattan((r,c), goal) + (0.25 if pi!=(0,0) else 0.0)
    heappush(pq, (h(start[0],start[1],(0,0)), 0.0, s))
    def w_cost(pi, drdc, rr, cc):
        turn = tau if (pi!=(0,0) and pi!=drdc) else 0.0
        tight = clr[rr][cc]/4.0
        return max(0.0, step + turn + alley*tight)
    while pq:
        f, g_cost, st = heappop(pq)
        if g_cost != dist.get(st, INF): continue
        r, c, pi = st
        if (r, c) == goal:
            path = []
            cur = st
            while cur in prev:
                (rr,cc,_), p = cur, prev[cur]
                path.append((rr,cc))
                cur = p
            (rr,cc,_) = cur
            path.append((rr,cc))
            return path[::-1]
        for rr,cc,dr,dc in neighbors_passages(g, r, c):
            if (rr,cc) in forbidden: continue
            wc = w_cost(pi,(dr,dc),rr,cc)
            ng = g_cost + wc
            ns = (rr,cc,(dr,dc))
            if ng < dist.get(ns, INF):
                dist[ns] = ng
                prev[ns] = st
                heappush(pq, (ng + h(rr,cc,(dr,dc)), ng, ns))
    return []

def greedy_meander(g, start, goal, rng, trials, bias_turn=0.0, bias_open=0.0, bias_goal=-0.7, forbidden=None, clr=None):
    forbidden = forbidden or set()
    if clr is None: clr = clearance_score(g)

    def reachable(snode, blocked):
        if snode in blocked or goal in blocked: return False
        Q = deque([snode]); seen = {snode}
        while Q:
            v = Q.popleft()
            if v == goal: return True
            r, c = v
            for rr,cc,_,_ in neighbors_passages(g, r, c):
                if (rr,cc) not in seen and (rr,cc) not in blocked and (rr,cc) not in forbidden:
                    seen.add((rr,cc))
                    Q.append((rr,cc))
        return False

    best = None
    for _ in range(trials):
        path = [start]; visited = {start}; prev_dir = None
        while path[-1] != goal:
            r, c = path[-1]; cand = []
            for rr,cc,dr,dc in neighbors_passages(g, r, c):
                if (rr,cc) in visited or (rr,cc) in forbidden: continue
                blocked = visited.copy(); blocked.add((rr,cc))
                if not reachable((rr,cc), blocked - {(rr,cc)}): continue
                turn = 1.0 if (prev_dir is not None and prev_dir != (dr,dc)) else 0.0
                open_bonus = 1.0 - (clr[rr][cc]/4.0)
                dgoal = manhattan((rr,cc), goal)
                score = (bias_turn*turn) + (bias_open*open_bonus) + (bias_goal*dgoal) + random.random()*0.05
                cand.append(((rr,cc,dr,dc), score))
            if not cand: break
            cand.sort(key=lambda x:x[1], reverse=True)
            rr,cc,dr,dc = random.choice(cand[:min(3,len(cand))])[0]
            prev_dir=(dr,dc)
            path.append((rr,cc))
            visited.add((rr,cc))
        if path and path[-1] == goal and ((best is None) or (len(path) > len(best))):
            best = path
    return best or []

# ──────────────────────────────────────────────────────────────────────────────
# Corridor graph (junctions as nodes, straight runs as edges)
# ──────────────────────────────────────────────────────────────────────────────
def _passage_deg(g, r, c):
    d = 0
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr,cc = r+dr, c+dc
        if 0 <= rr < len(g) and 0 <= cc < len(g[0]) and not g[rr][cc]:
            d += 1
    return d

def build_corridor_graph(g, start, end):
    R, C = len(g), len(g[0])
    is_node = [[False]*C for _ in range(R)]
    nodes = []; idx_of = {}

    def mark(rc):
        if rc not in idx_of:
            idx_of[rc] = len(nodes)
            nodes.append(rc)
            is_node[rc[0]][rc[1]] = True

    mark(tuple(start)); mark(tuple(end))
    for r in range(1, R-1):
        for c in range(1, C-1):
            if not g[r][c] and _passage_deg(g, r, c) != 2:
                mark((r, c))

    adj = {i: [] for i in range(len(nodes))}

    def march(r, c, dr, dc):
        cells = []; pr, pc = r, c
        while True:
            nr, nc = pr+dr, pc+dc
            if not (0 <= nr < R and 0 <= nc < C): break
            if g[nr][nc]: break
            cells.append((nr, nc))
            if is_node[nr][nc] or _passage_deg(g, nr, nc) != 2:
                return (nr, nc), cells
            pr, pc = nr, nc
        return None, cells

    for i, (r, c) in enumerate(nodes):
        for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
            rr, cc = r+dr, c+dc
            if 0 <= rr < R and 0 <= cc < C and not g[rr][cc]:
                hit, cells = march(r, c, dr, dc)
                if not hit or not cells:
                    continue
                j = idx_of.get(hit)
                if j is None:
                    continue
                adj[i].append((j, len(cells), (dr,dc), cells))
                adj[j].append((i, len(cells), (-dr,-dc), list(reversed(cells))))
    return {"nodes": nodes, "adj": adj}

def _node_heuristic(nodes, A, B): return manhattan(nodes[A], nodes[B])

def graph_shortest(graph, si, ei):
    nodes, adj = graph["nodes"], graph["adj"]
    INF = 10**12
    dist = [INF]*len(nodes); prev=[None]*len(nodes); prev_edge=[None]*len(nodes)
    dist[si] = 0; pq = [(0, si)]
    while pq:
        d, i = heappop(pq)
        if d != dist[i]: continue
        if i == ei: break
        for (j, L, dir_, cells) in adj[i]:
            nd = d + L
            if nd < dist[j]:
                dist[j] = nd; prev[j] = i; prev_edge[j] = (i,j,dir_,cells)
                heappush(pq, (nd, j))
    if dist[ei] >= INF: return []
    chain=[]; cur=ei
    while cur != si:
        e = prev_edge[cur]
        if e is None: break
        chain.append(e); cur=prev[cur]
    chain.reverse()
    if not chain: return []
    cells=[nodes[si]]
    for (i,j,dir_,ecs) in chain: cells.extend(ecs)
    return cells

def graph_smooth_turnaware(graph, si, ei, tau=0.9):
    nodes, adj = graph["nodes"], graph["adj"]
    INF = 10**12
    s = (si,(0,0)); dist = {s:0.0}; prev={}; prev_edge={}; pq=[(0.0,s)]
    def tcost(pdir, ndir): return tau if (pdir!=(0,0) and pdir!=ndir) else 0.0
    while pq:
        d, st = heappop(pq)
        if d != dist.get(st, INF): continue
        i, pdir = st
        if i == ei:
            chain=[]; cur=st
            while cur in prev:
                e=prev_edge[cur]; chain.append(e); cur=prev[cur]
            chain.reverse()
            if not chain: return [nodes[si], nodes[ei]]
            cells=[nodes[si]]
            for (a,b,dir_,ecs) in chain: cells.extend(ecs)
            return cells
        for (j, L, dir_, ecs) in adj[i]:
            nd = d + L + tcost(pdir, dir_)
            ns = (j, dir_)
            if nd < dist.get(ns, INF):
                dist[ns] = nd; prev[ns] = st; prev_edge[ns] = (i,j,dir_,ecs)
                heappush(pq, (nd, ns))
    return []

def graph_meander_long(graph, si, ei, rng, trials=200, bias_turn=0.6, bias_len=0.6, bias_goal=-0.6):
    nodes, adj = graph["nodes"], graph["adj"]
    best=None; best_score=(-1,-1)
    def reach_ok(start_i, end_i, blocked):
        Q=deque([start_i]); seen=set(blocked)|{start_i}
        while Q:
            i=Q.popleft()
            if i==end_i: return True
            for (j,_,_,_) in adj[i]:
                if j not in seen: seen.add(j); Q.append(j)
        return False
    for _ in range(trials):
        path=[si]; visited={si}; prev_dir=None; tcount=0
        while path[-1]!=ei:
            i=path[-1]; cand=[]
            for (j,L,dir_,ecs) in adj[i]:
                if j in visited: continue
                if not reach_ok(j, ei, visited): continue
                dgoal=_node_heuristic(nodes,j,ei)
                turn = 1.0 if (prev_dir is not None and prev_dir!=dir_) else 0.0
                score=(bias_len*L)+(bias_turn*turn)+(bias_goal*dgoal)+rng.random()*0.05
                cand.append((score,j,dir_,L))
            if not cand: break
            cand.sort(key=lambda x:x[0], reverse=True)
            _, j, dir_, L = random.choice(cand[:min(3,len(cand))])
            if prev_dir is not None and prev_dir!=dir_: tcount+=1
            path.append(j); visited.add(j); prev_dir=dir_
        if path and path[-1]==ei:
            cells = _expand_graph_nodepath_to_cells(graph, path)
            sc=(len(cells), tcount)
            if sc>best_score: best=path; best_score=sc
    if not best: return []
    return _expand_graph_nodepath_to_cells(graph, best)

def graph_zigzaggy(graph, si, ei, rng, trials=200):
    nodes, adj = graph["nodes"], graph["adj"]
    best=None; best_score=(-1,-1)
    def reach_ok(start_i, end_i, blocked):
        Q=deque([start_i]); seen=set(blocked)|{start_i}
        while Q:
            i=Q.popleft()
            if i==end_i: return True
            for (j,_,_,_) in adj[i]:
                if j not in seen: seen.add(j); Q.append(j)
        return False
    for _ in range(trials):
        path=[si]; visited={si}; prev_dir=None; tcount=0
        while path[-1]!=ei:
            i=path[-1]; cand=[]
            for (j,L,dir_,ecs) in adj[i]:
                if j in visited: continue
                if not reach_ok(j, ei, visited): continue
                turn = 1.0 if (prev_dir is not None and prev_dir!=dir_) else 0.0
                score=(1.2*turn)+(0.1*L)+rng.random()*0.05
                cand.append((score,j,dir_,L))
            if not cand: break
            cand.sort(key=lambda x:x[0], reverse=True)
            _, j, dir_, L = random.choice(cand[:min(3,len(cand))])
            if prev_dir is not None and prev_dir!=dir_: tcount+=1
            path.append(j); visited.add(j); prev_dir=dir_
        if path and path[-1]==ei:
            cells = _expand_graph_nodepath_to_cells(graph, path)
            sc=(tcount, len(cells))
            if sc>best_score: best=path; best_score=sc
    if not best: return []
    return _expand_graph_nodepath_to_cells(graph, best)

def _expand_graph_nodepath_to_cells(graph, node_path):
    if not node_path: return []
    cells=[graph["nodes"][node_path[0]]]
    for a, b in zip(node_path, node_path[1:]):
        hit=None
        for (j,L,dir_,ecs) in graph["adj"][a]:
            if j == b:
                hit = ecs; break
        if not hit: return []
        cells.extend(hit)
    return cells

def _count_turns_on_cells(cells):
    if len(cells) < 3: return 0
    def dir_of(a,b): return (b[0]-a[0], b[1]-a[1])
    turns=0; prev=dir_of(cells[0], cells[1])
    for i in range(1, len(cells)-1):
        d=dir_of(cells[i], cells[i+1])
        if d != prev: turns += 1
        prev = d
    return turns

# ──────────────────────────────────────────────────────────────────────────────
# Similarity / overlap control
# ──────────────────────────────────────────────────────────────────────────────
def jaccard_similarity(A, B, ignore):
    a=set(map(tuple,A)) - ignore; b=set(map(tuple,B)) - ignore
    if not a and not b: return 1.0
    return len(a & b) / max(1, len(a | b))

def is_too_similar(candidate, existing, start, end, thresh):
    ignore={start,end}
    for ent in existing:
        if jaccard_similarity(candidate, ent["cells"], ignore) >= thresh:
            return True
    return False

def _shared_fraction(A_cells, B_cells):
    A=set(map(tuple, A_cells[1:-1])); B=set(map(tuple, B_cells[1:-1]))
    if not A: return 0.0
    return len(A & B)/len(A)

def overlap_ok(candidate, existing, min_frac, max_frac):
    if not existing: return True
    best=0.0
    for ent in existing:
        f=_shared_fraction(candidate, ent["cells"])
        best=max(best, f)
    return (best >= min_frac) and (best <= max_frac)

# ──────────────────────────────────────────────────────────────────────────────
# Unique-route wrappers (grid + graph)
# ──────────────────────────────────────────────────────────────────────────────
def simple_route_grid(bitmap, start, end, solver, params, rng, trials, clr):
    if solver == "DIJK":
        return dijkstra_cost(bitmap, start, end, params, forbidden=None, clr=clr)
    else:
        return greedy_meander(bitmap, start, end, rng, trials,
                              bias_turn=params.get("bias_turn",0.0),
                              bias_open=params.get("bias_open",0.0),
                              bias_goal=params.get("bias_goal",-0.7),
                              forbidden=None, clr=clr)

def ensure_unique_route(g, start, end, params, existing, rng, max_tries, thresh, clr=None):
    cand = dijkstra_cost(g, start, end, params, forbidden=None, clr=clr)
    if not cand: return []
    if not is_too_similar(cand, existing, start, end, thresh): return cand
    for _ in range(max_tries):
        core=[tuple(rc) for rc in cand[1:-1]]
        if not core: break
        forbid=set(random.sample(core, max(1,int(0.15*len(core)))))
        alt=dijkstra_cost(g, start, end, params, forbidden=forbid, clr=clr)
        if alt and not is_too_similar(alt, existing, start, end, thresh): return alt
        if alt: cand=alt
    return []

def ensure_unique_route_meander(g, start, end, rng, trials, existing, start_bias, thresh, max_tries, clr=None):
    cand = greedy_meander(g, start, end, rng, trials, **start_bias, forbidden=None, clr=clr)
    if not cand: return []
    if not is_too_similar(cand, existing, start, end, thresh): return cand
    for _ in range(max_tries):
        core=[tuple(rc) for rc in cand[1:-1]]
        if not core: break
        forbid=set(random.sample(core, max(1,int(0.15*len(core)))))
        alt=greedy_meander(g, start, end, rng, max(50,trials//2), **start_bias, forbidden=forbid, clr=clr)
        if alt and not is_too_similar(alt, existing, start, end, thresh): return alt
        if alt: cand=alt
    return []

# Graph-based variants
def graph_shortest_with_penalty(graph, si, ei, penalize_count=3):
    nodes, adj = graph["nodes"], graph["adj"]
    edges=[]
    for i in adj:
        for (j,_,_,_) in adj[i]:
            if i < j: edges.append((i,j))
    rng=random.Random()
    penal=set(rng.sample(edges, min(penalize_count, len(edges))))
    INF=10**9
    dist=[INF]*len(nodes); prev=[None]*len(nodes); prev_edge=[None]*len(nodes)
    dist[si]=0; pq=[(0,si)]
    while pq:
        d,i=heappop(pq)
        if d!=dist[i]: continue
        if i==ei: break
        for (j,L,dir_,cells) in adj[i]:
            nd=d + L + ((L*0.8) if ((min(i,j),max(i,j)) in penal) else 0.0)
            if nd < dist[j]:
                dist[j]=nd; prev[j]=i; prev_edge[j]=(i,j,dir_,cells)
                heappush(pq,(nd,j))
    if dist[ei] >= INF: return []
    chain=[]; cur=ei
    while cur != si:
        e = prev_edge[cur]
        if e is None: break
        chain.append(e); cur=prev[cur]
    chain.reverse()
    if not chain: return []
    cells=[nodes[si]]
    for (i,j,dir_,ecs) in chain: cells.extend(ecs)
    return cells

def ensure_unique_route_graph_shortest(graph, si, ei, existing, start, end, rng, max_tries, thresh):
    cand = graph_shortest(graph, si, ei)
    if not cand: return []
    if not is_too_similar(cand, existing, start, end, thresh): return cand
    for _ in range(max_tries):
        alt = graph_shortest_with_penalty(graph, si, ei, penalize_count=3)
        if alt and not is_too_similar(alt, existing, start, end, thresh): return alt
    return []

def ensure_unique_route_graph_smooth(graph, si, ei, tau, existing, start, end, rng, max_tries, thresh):
    cand = graph_smooth_turnaware(graph, si, ei, tau=tau)
    if not cand: return []
    if not is_too_similar(cand, existing, start, end, thresh): return cand
    for _ in range(max_tries):
        alt = graph_smooth_turnaware(graph, si, ei, tau=tau*1.15)
        if alt and not is_too_similar(alt, existing, start, end, thresh): return alt
    return []

def ensure_unique_route_graph_meander(graph, si, ei, rng, trials, existing, thresh, max_tries):
    cand = graph_meander_long(graph, si, ei, rng, trials=trials)
    if not cand: return []
    if not is_too_similar(cand, existing, graph["nodes"][si], graph["nodes"][ei], thresh): return cand
    for _ in range(max_tries):
        alt = graph_meander_long(graph, si, ei, rng, trials=max(50, trials//2))
        if alt and not is_too_similar(alt, existing, graph["nodes"][si], graph["nodes"][ei], thresh): return alt
    return []

def ensure_unique_route_graph_zigzag(graph, si, ei, rng, trials, existing, thresh, max_tries):
    cand = graph_zigzaggy(graph, si, ei, rng, trials=trials)
    if not cand: return []
    if not is_too_similar(cand, existing, graph["nodes"][si], graph["nodes"][ei], thresh): return cand
    for _ in range(max_tries):
        alt = graph_zigzaggy(graph, si, ei, rng, trials=max(50, trials//2))
        if alt and not is_too_similar(alt, existing, graph["nodes"][si], graph["nodes"][ei], thresh): return alt
    return []

# ──────────────────────────────────────────────────────────────────────────────
# Drawing helpers (tiles + batched prisms)
# ──────────────────────────────────────────────────────────────────────────────
def _build_batched_tile_mesh(name_prefix, positions, color, geom, base_z):
    cell_w, cell_h, off_x, off_y, tile_xy, tile_h, _tile_z = geom
    hw = tile_xy * 0.5
    verts=[]; faces=[]
    for rc in positions:
        x,y = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
        v0=Vector((x-hw, y-hw, base_z)); v1=Vector((x+hw, y-hw, base_z))
        v2=Vector((x+hw, y+hw, base_z)); v3=Vector((x-hw, y+hw, base_z))
        idx=len(verts); verts.extend([v0,v1,v2,v3]); faces.append([idx,idx+1,idx+2,idx+3])
    if not faces: return None
    top_offset = Vector((0,0,geom[5]))
    n=len(verts); verts.extend([v+top_offset for v in verts])
    faces_top = [[i+n for i in f] for f in faces]
    sides=[]
    for f in faces:
        a,b,c,d=f; at,bt,ct,dt=a+n,b+n,c+n,d+n
        sides.extend([[a,b,bt,at],[b,c,ct,bt],[c,d,dt,ct],[d,a,at,dt]])
    mesh=bpy.data.meshes.new(name_prefix+"_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces+faces_top+sides); mesh.update()
    ob=bpy.data.objects.new(name_prefix, mesh)
    col=get_collection("maze_paths"); col.objects.link(ob)
    mat=ensure_mat(f"{name_prefix}_Mat", color)
    if ob.data.materials: ob.data.materials[0]=mat
    else: ob.data.materials.append(mat)
    return ob

def draw_tiles_for_path(name_prefix, path, color, geom, skip_cells):
    base_z = geom[6]
    positions = [tuple(rc) for rc in path if tuple(rc) not in skip_cells]
    _build_batched_tile_mesh(name_prefix, positions, color, geom, base_z)

def draw_tiles_for_cells(name_prefix, cells, color, geom):
    base_z = geom[6] + 0.002
    positions = [tuple(rc) for rc in sorted(cells)]
    _build_batched_tile_mesh(name_prefix, positions, color, geom, base_z)

def build_batched_prisms(name, rects_world, heights, color, target_col, mat_name=None):
    # builds prisms from Z=0 to each height
    verts=[]; faces=[]
    for (x0,x1,y0,y1), z1 in zip(rects_world, heights):
        z0=0.0
        b0=Vector((x0,y0,z0)); b1=Vector((x1,y0,z0))
        b2=Vector((x1,y1,z0)); b3=Vector((x0,y1,z0))
        t0=Vector((x0,y0,z1)); t1=Vector((x1,y0,z1))
        t2=Vector((x1,y1,z1)); t3=Vector((x0,y1,z1))
        idx=len(verts); verts.extend([b0,b1,b2,b3,t0,t1,t2,t3])
        faces.extend([
            [idx+0,idx+1,idx+5,idx+4],
            [idx+1,idx+2,idx+6,idx+5],
            [idx+2,idx+3,idx+7,idx+6],
            [idx+3,idx+0,idx+4,idx+7],
            [idx+4,idx+5,idx+6,idx+7]
        ])
    if not faces: return None
    mesh=bpy.data.meshes.new(name+"_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces); mesh.update()
    ob=bpy.data.objects.new(name, mesh); target_col.objects.link(ob)
    mat=ensure_mat(mat_name or (name+"_Mat"), color)
    if ob.data.materials: ob.data.materials[0]=mat
    else: ob.data.materials.append(mat)
    return ob

def build_street_ribbons(bitmap, H, W, cell_w, cell_h, off_x, off_y, width_factor, height, color, target_col):
    wf = max(0.2, min(1.0, width_factor))
    w = cell_w * wf; h = cell_h * wf
    half_w = w*0.5; half_h=h*0.5
    verts=[]; faces=[]
    for r in range(H):
        for c in range(W):
            if bitmap[r][c]: continue
            x,y = rc_to_world(off_x, off_y, cell_w, cell_h, (r,c))
            v0=Vector((x-half_w, y-half_h, 0.0))
            v1=Vector((x+half_w, y-half_h, 0.0))
            v2=Vector((x+half_w, y+half_h, 0.0))
            v3=Vector((x-half_w, y+half_h, 0.0))
            idx=len(verts); verts.extend([v0,v1,v2,v3]); faces.append([idx,idx+1,idx+2,idx+3])
    if not faces: return None
    top_offset = Vector((0,0,height))
    n=len(verts); verts.extend([v+top_offset for v in verts])
    faces_top = [[i+n for i in f] for f in faces]
    sides=[]
    for f in faces:
        a,b,c,d=f; at,bt,ct,dt=a+n,b+n,c+n,d+n
        sides.extend([[a,b,bt,at],[b,c,ct,bt],[c,d,dt,ct],[d,a,at,dt]])
    mesh=bpy.data.meshes.new("CityStreets_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces+faces_top+sides); mesh.update()
    ob=bpy.data.objects.new("CityStreets", mesh); target_col.objects.link(ob)
    mat=ensure_mat("CityStreets_Mat", color)
    if ob.data.materials: ob.data.materials[0]=mat
    else: ob.data.materials.append(mat)
    return ob

def build_plaza_meshes(plaza_cells, cell_w, cell_h, off_x, off_y, thickness, color, target_col):
    if not plaza_cells: return []
    plaza_cells=set(plaza_cells)
    comps=[]; seen=set(); dirs=[(1,0),(-1,0),(0,1),(0,-1)]
    for rc in list(plaza_cells):
        if rc in seen: continue
        q=[rc]; seen.add(rc); comp=[rc]; i=0
        while i<len(q):
            r,c=q[i]; i+=1
            for dr,dc in dirs:
                v=(r+dr,c+dc)
                if v in plaza_cells and v not in seen:
                    seen.add(v); q.append(v); comp.append(v)
        comps.append(comp)
    out=[]
    for k,comp in enumerate(comps,1):
        verts=[]; faces=[]; half_w=cell_w*0.5; half_h=cell_h*0.5
        for (r,c) in comp:
            x,y = rc_to_world(off_x, off_y, cell_w, cell_h, (r,c))
            v0=Vector((x-half_w, y-half_h, 0.0))
            v1=Vector((x+half_w, y-half_h, 0.0))
            v2=Vector((x+half_w, y+half_h, 0.0))
            v3=Vector((x-half_w, y+half_h, 0.0))
            idx=len(verts); verts.extend([v0,v1,v2,v3]); faces.append([idx,idx+1,idx+2,idx+3])
        if not faces: continue
        top_offset=Vector((0,0,thickness))
        n=len(verts); verts.extend([v+top_offset for v in verts])
        faces_top=[[i+n for i in f] for f in faces]
        sides=[]
        for f in faces:
            a,b,c,d=f; at,bt,ct,dt=a+n,b+n,c+n,d+n
            sides.extend([[a,b,bt,at],[b,c,ct,bt],[c,d,dt,ct],[d,a,at,dt]])
        mesh=bpy.data.meshes.new(f"Plaza_{k}_Mesh")
        mesh.from_pydata([tuple(v) for v in verts], [], faces+faces_top+sides); mesh.update()
        ob=bpy.data.objects.new(f"Plaza_{k}", mesh); target_col.objects.link(ob)
        mat=ensure_mat("Plaza_Mat", color)
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        out.append(ob)
    return out

# ──────────────────────────────────────────────────────────────────────────────
# City building generator (districts, variable footprints, podium+tower, roofs)
# ──────────────────────────────────────────────────────────────────────────────
def _lot_rect_from_block(off_x, off_y, cell_w, cell_h, r,c,h,w, gap):
    x0 = off_x + c*cell_w; y0 = -(off_y + r*cell_h)
    x1 = x0 + w*cell_w;     y1 = y0 - h*cell_h
    sh = max(0.0, gap*0.5)
    return (x0+sh, x1-sh, y0+sh, y1-sh)  # (x0,x1,y0,y1)

def _center_of_rect(r): x0,x1,y0,y1=r; return (0.5*(x0+x1), 0.5*(y0+y1))

def _nearest_seed_idx(pt, seeds):
    px,py=pt; best=-1; bd=1e18
    for i,(sx,sy) in enumerate(seeds):
        d=(px-sx)*(px-sx)+(py-sy)*(py-sy)
        if d<bd: bd=d; best=i
    return best

def _district_seeds(world_bounds, count, rng):
    (X0,X1,Y0,Y1)=world_bounds
    seeds=[]
    for _ in range(count):
        sx = rng.uniform(X0, X1)
        sy = rng.uniform(Y0, Y1)
        seeds.append((sx,sy))
    return seeds

def _shrink_rect(rect, frac_w, frac_h, align_cxcy=None):
    x0,x1,y0,y1=rect
    w = (x1-x0)*frac_w
    h = (y1-y0)*frac_h
    if align_cxcy is None:
        cx = 0.5*(x0+x1); cy = 0.5*(y0+y1)
    else:
        cx, cy = align_cxcy
        cx = max(x0 + 0.5*w, min(x1 - 0.5*w, cx))
        cy = max(y0 + 0.5*h, min(y1 - 0.5*h, cy))
    nx0 = cx - 0.5*w; nx1 = cx + 0.5*w
    ny0 = cy - 0.5*h; ny1 = cy + 0.5*h
    return (nx0, nx1, ny0, ny1)

def _roof_batches_with_tops(lots_top_rects, roof_probs, roof_height, color, target_col, rng):
    """Create roof geometry at top-of-tower elevation. Batches by type."""
    if not lots_top_rects or roof_height <= 0.0:
        return []
    classes = {"FLAT":[], "GABLE_X":[], "GABLE_Y":[], "HIP":[]}
    types = ["FLAT","GABLE_X","GABLE_Y","HIP"]
    probs = [max(0.0, roof_probs.get(k,0.25)) for k in types]
    s = sum(probs) or 1.0
    probs = [p/s for p in probs]
    for rect, top_z in lots_top_rects:
        t = rng.choices(types, weights=probs, k=1)[0]
        classes[t].append((rect, top_z))

    out=[]
    def add_flat(items, name):
        if not items: return
        verts=[]; faces=[]
        for (x0,x1,y0,y1), top in items:
            z0 = top; z1 = top + roof_height
            b0=Vector((x0,y0,z0)); b1=Vector((x1,y0,z0))
            b2=Vector((x1,y1,z0)); b3=Vector((x0,y1,z0))
            t0=Vector((x0,y0,z1)); t1=Vector((x1,y0,z1))
            t2=Vector((x1,y1,z1)); t3=Vector((x0,y1,z1))
            idx=len(verts); verts.extend([b0,b1,b2,b3,t0,t1,t2,t3])
            faces.extend([
                [idx+0,idx+1,idx+5,idx+4],
                [idx+1,idx+2,idx+6,idx+5],
                [idx+2,idx+3,idx+7,idx+6],
                [idx+3,idx+0,idx+4,idx+7],
                [idx+4,idx+5,idx+6,idx+7]
            ])
        mesh=bpy.data.meshes.new(name+"_Mesh")
        mesh.from_pydata([tuple(v) for v in verts], [], faces); mesh.update()
        ob=bpy.data.objects.new(name, mesh); target_col.objects.link(ob)
        mat=ensure_mat(name+"_Mat", color)
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        out.append(ob)

    def add_gable(items, along_x, name):
        if not items: return
        verts=[]; faces=[]
        for (x0,x1,y0,y1), top in items:
            apex_h = top + roof_height
            p0=Vector((x0,y0,top)); p1=Vector((x1,y0,top)); p2=Vector((x1,y1,top)); p3=Vector((x0,y1,top))
            if along_x:
                ridge0=Vector((x0,0.5*(y0+y1),apex_h)); ridge1=Vector((x1,0.5*(y0+y1),apex_h))
                idx=len(verts); verts.extend([p0,p1,p2,p3,ridge0,ridge1])
                faces.extend([
                    [idx+0,idx+1,idx+5,idx+4],
                    [idx+2,idx+3,idx+4,idx+5],
                    [idx+1,idx+2,idx+5],
                    [idx+3,idx+0,idx+4],
                ])
            else:
                ridge0=Vector((0.5*(x0+x1),y0,apex_h)); ridge1=Vector((0.5*(x0+x1),y1,apex_h))
                idx=len(verts); verts.extend([p0,p1,p2,p3,ridge0,ridge1])
                faces.extend([
                    [idx+1,idx+2,idx+5,idx+4],
                    [idx+3,idx+0,idx+4,idx+5],
                    [idx+2,idx+3,idx+5],
                    [idx+0,idx+1,idx+4],
                ])
        mesh=bpy.data.meshes.new(name+"_Mesh")
        mesh.from_pydata([tuple(v) for v in verts], [], faces); mesh.update()
        ob=bpy.data.objects.new(name, mesh); target_col.objects.link(ob)
        mat=ensure_mat(name+"_Mat", color)
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        out.append(ob)

    def add_hip(items, name):
        if not items: return
        verts=[]; faces=[]
        for (x0,x1,y0,y1), top in items:
            apex=Vector(((x0+x1)*0.5,(y0+y1)*0.5, top+roof_height))
            p0=Vector((x0,y0,top)); p1=Vector((x1,y0,top)); p2=Vector((x1,y1,top)); p3=Vector((x0,y1,top))
            idx=len(verts); verts.extend([p0,p1,p2,p3,apex])
            faces.extend([[idx+0,idx+1,idx+4],[idx+1,idx+2,idx+4],[idx+2,idx+3,idx+4],[idx+3,idx+0,idx+4]])
        mesh=bpy.data.meshes.new(name+"_Mesh")
        mesh.from_pydata([tuple(v) for v in verts], [], faces); mesh.update()
        ob=bpy.data.objects.new(name, mesh); target_col.objects.link(ob)
        mat=ensure_mat(name+"_Mat", color)
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        out.append(ob)

    add_flat(classes["FLAT"], "Roof_Flat")
    add_gable(classes["GABLE_X"], True,  "Roof_GableX")
    add_gable(classes["GABLE_Y"], False, "Roof_GableY")
    add_hip(classes["HIP"], "Roof_Hip")
    return out

def build_city_with_districts(blocks_cells, cell_w, cell_h, off_x, off_y,
                              lot_min, lot_max, lot_gap,
                              podium_height,
                              podium_min_frac, podium_max_frac,
                              tower_min_frac, tower_max_frac,
                              hmin, hmax, district_count, district_colors,
                              roof_probs, roof_height, roof_color,
                              target_col, rng):
    """
    - Subdivide each wall-block area into lots.
    - For each lot, create a podium (variable footprint) and a tower (variable footprint),
      both entirely inside the lot, i.e., never encroaching on streets.
    - Assign towers to districts (Voronoi over lot centers), batch by district color.
    - Roofs are placed at top-of-tower heights (flat/gable/hip), batched by type.
    """
    if not blocks_cells:
        return []

    # World bounds
    world_x = [off_x + (c+w)*cell_w for (_,c,_,w) in blocks_cells] + [off_x + c*cell_w for (_,c,_,_) in blocks_cells]
    world_y = [-(off_y + (r+h)*cell_h) for (r,_,h,_) in blocks_cells] + [-(off_y + r*cell_h) for (r,_,_,_) in blocks_cells]
    bounds=(min(world_x), max(world_x), min(world_y), max(world_y))
    seeds=_district_seeds(bounds, district_count, rng)

    podium_rects=[]; podium_heights=[]
    districts_towers = {i: [] for i in range(district_count)}  # list of rects
    towers_heights   = {i: [] for i in range(district_count)}  # top z per rect
    tower_rects_top  = []  # (rect, top_z) for roofs

    # subdivide and populate lots
    for (r,c,h,w) in blocks_cells:
        base_rect = _lot_rect_from_block(off_x, off_y, cell_w, cell_h, r,c,h,w, lot_gap)
        # Split into lots using random chunk sizes between lot_min..lot_max cells
        def split_axis(total_cells):
            parts=[]
            remain=total_cells
            while remain>0:
                k = min(remain, rng.randint(lot_min, lot_max))
                parts.append(k); remain -= k
            return parts
        xparts = split_axis(max(1,w))
        yparts = split_axis(max(1,h))

        x0,x1,y0,y1 = base_rect
        curx = x0
        for kx in xparts:
            cury = y1
            lot_wm = kx*cell_w
            for ky in yparts:
                lot_hm = ky*cell_h
                lx0 = curx; lx1 = curx + lot_wm
                ly1 = cury; ly0 = cury - lot_hm
                lot_rect = (lx0, lx1, ly0, ly1)

                # PODIUM footprint variability (fraction of lot)
                pf_w = rng.uniform(max(0.1, podium_min_frac), min(1.0, podium_max_frac))
                pf_h = rng.uniform(max(0.1, podium_min_frac), min(1.0, podium_max_frac))
                cx, cy = _center_of_rect(lot_rect)
                jitter_w = (lot_wm*(1.0-pf_w))*0.4
                jitter_h = (lot_hm*(1.0-pf_h))*0.4
                jittered_cx = cx + rng.uniform(-jitter_w, jitter_w)
                jittered_cy = cy + rng.uniform(-jitter_h, jitter_h)
                podium_rect = _shrink_rect(lot_rect, pf_w, pf_h, align_cxcy=(jittered_cx, jittered_cy))
                if podium_rect[0] < podium_rect[1] and podium_rect[2] < podium_rect[3]:
                    podium_rects.append(podium_rect)
                    podium_heights.append(max(0.0, min(hmax, podium_height)))

                # TOWER footprint variability (fraction of lot)
                tf_w = rng.uniform(max(0.1, tower_min_frac), min(1.0, tower_max_frac))
                tf_h = rng.uniform(max(0.1, tower_min_frac), min(1.0, tower_max_frac))
                jitter_wt = (lot_wm*(1.0-tf_w))*0.45
                jitter_ht = (lot_hm*(1.0-tf_h))*0.45
                jittered_cx_t = cx + rng.uniform(-jitter_wt, jitter_wt)
                jittered_cy_t = cy + rng.uniform(-jitter_ht, jitter_ht)
                tower_rect = _shrink_rect(lot_rect, tf_w, tf_h, align_cxcy=(jittered_cx_t, jittered_cy_t))
                if tower_rect[0] >= tower_rect[1] or tower_rect[2] >= tower_rect[3]:
                    continue
                # assign district by tower center
                tcx,tcy = _center_of_rect(tower_rect)
                di = _nearest_seed_idx((tcx,tcy), seeds)
                zh = rng.uniform(max(hmin, podium_height), hmax)
                districts_towers[di].append(tower_rect)
                towers_heights[di].append(zh)
                tower_rects_top.append((tower_rect, zh))

            curx += lot_wm

    out=[]
    # Podiums (one batched mesh)
    if podium_rects:
        ob = build_batched_prisms("CityPodiums", podium_rects, podium_heights, color=(0.75,0.75,0.78,1), target_col=target_col, mat_name="CityPodium_Mat")
        if ob: out.append(ob)

    # Towers per district (batched, colored per district)
    for di, rects in districts_towers.items():
        if not rects: continue
        col = district_colors[di % len(district_colors)]
        heights = towers_heights[di]
        ob = build_batched_prisms(f"CityTowers_D{di+1}", rects, heights, color=tuple(col), target_col=target_col, mat_name=f"District_{di+1}_Mat")
        if ob: out.append(ob)

    # Roofs at top-of-tower
    if tower_rects_top and roof_height > 0.0:
        _roof_batches_with_tops(tower_rects_top, roof_probs, roof_height, roof_color, target_col, rng)

    return out

# ──────────────────────────────────────────────────────────────────────────────
# Properties
# ──────────────────────────────────────────────────────────────────────────────
class MMM_Props(PropertyGroup):
    # Maze size & randomness
    rows: IntProperty(name="Rows", default=22, min=5, soft_max=300, description="Logical maze rows (cells → grid height = 2*rows+1)")
    cols: IntProperty(name="Cols", default=34, min=5, soft_max=300, description="Logical maze cols (cells → grid width = 2*cols+1)")
    randomize: BoolProperty(name="Random Seed", default=True, description="Randomize seed each run")
    seed: IntProperty(name="Seed", default=12345, min=0, description="Fixed seed when Random Seed is off")

    # Geometry & floor
    cell_w: FloatProperty(name="Cell W", default=2.5, min=0.05, description="World width per grid cell (meters)")
    cell_h: FloatProperty(name="Cell H", default=2.5, min=0.05, description="World height per grid cell (meters)")
    height_min: FloatProperty(name="Wall H min", default=7.0, min=0.05)
    height_max: FloatProperty(name="Wall H max", default=20.0, min=0.05)
    uniform_height: BoolProperty(name="Uniform Height", default=False)
    make_floor: BoolProperty(name="Make Floor", default=True)
    floor_thickness: FloatProperty(name="Floor Thickness", default=0.2, min=0.0)

    # Materials (classic maze)
    wall_color: FloatVectorProperty(name="Block/Wall Color", subtype='COLOR', size=4, default=(0.85,0.86,0.9,1))
    wall_mat_name: StringProperty(name="Block/Wall Material", default="MazeWall")
    floor_mat_name: StringProperty(name="Floor Material", default="MazeFloor")

    # Path tiles
    tile_size: FloatProperty(name="Tile Size", default=0.90, min=0.1, max=1.5)
    tile_height: FloatProperty(name="Tile Height", default=0.05, min=0.005)
    tile_z_offset: FloatProperty(name="Tile Z Offset", default=0.03, min=0.0)
    start_color: FloatVectorProperty(name="Start Color", subtype='COLOR', size=4, default=(1.0,0.25,0.25,1.0))
    col_intersection: FloatVectorProperty(name="Intersection Color", subtype='COLOR', size=4, default=(0.7,0.2,0.2,1))

    # Styles
    use_purist: BoolProperty(name="Purist", default=True, description="Shortest path with minimal steps")
    col_purist: FloatVectorProperty(name="Purist Color", subtype='COLOR', size=4, default=(0.2,0.7,1.0,1))
    use_smooth: BoolProperty(name="Smooth", default=True, description="Penalize turns; favor straighter corridors")
    col_smooth: FloatVectorProperty(name="Smooth Color", subtype='COLOR', size=4, default=(0.4,1.0,0.8,1))
    use_explorative: BoolProperty(name="Explorative", default=True, description="Detour-friendly without repeats; scenic")
    col_explorative: FloatVectorProperty(name="Explorative Color", subtype='COLOR', size=4, default=(1.0,0.85,0.2,1))
    use_zigzag: BoolProperty(name="Zigzag", default=False, description="Turn-hungry; prefers frequent direction changes")
    col_zigzag: FloatVectorProperty(name="Zigzag Color", subtype='COLOR', size=4, default=(1.0,0.5,0.9,1))
    explorative_trials: IntProperty(name="Greedy Trials", default=800, min=100, soft_max=6000)

    # Uniqueness & Intersections
    enforce_unique: BoolProperty(name="Enforce Uniqueness", default=True, description="Avoid near-duplicate paths")
    unique_jaccard_max: FloatProperty(name="Max Similarity", default=0.85, min=0.5, max=0.99)
    unique_reroute_tries: IntProperty(name="Reroute Tries", default=8, min=0, max=50)
    enforce_overlap: BoolProperty(name="Control Intersections", default=True, description="Force shared fraction to be within bounds")
    min_shared_frac: FloatProperty(name="Min Shared Fraction", default=0.05, min=0.0, max=0.5)
    max_shared_frac: FloatProperty(name="Max Shared Fraction", default=0.35, min=0.05, max=0.6)

    # Append
    append_paths: BoolProperty(name="Append New Paths", default=False, description="Append instead of replacing current paths")

    # Performance
    use_graph_accel: BoolProperty(name="Fast Graph Acceleration", default=True, description="Use corridor graph to speed up routing")
    fast_mode: BoolProperty(name="Extra Fast Mode", default=False, description="Reduce trials/reroutes for speed")

    # City Mode toggles
    use_city_mode: BoolProperty(name="City Mode (Blocks)", default=False, description="Replace wall volumes with city blocks & lots")
    city_grid_jitter: FloatProperty(name="Grid Irregularity", default=0.15, min=0.0, max=0.6)
    city_loop_ratio: FloatProperty(name="Loop Ratio", default=0.12, min=0.0, max=0.5)
    city_culdesac_prob: FloatProperty(name="Cul-de-Sac Chance", default=0.10, min=0.0, max=0.6)
    city_culdesac_len: IntProperty(name="Cul-de-Sac Max Len (cells)", default=5, min=1, soft_max=15)
    city_plaza_prob: FloatProperty(name="Plaza Chance", default=0.08, min=0.0, max=0.4)
    city_plaza_minmax: IntProperty(name="Plaza Size (cells edge)", default=3, min=2, soft_max=8)
    plaza_thickness: FloatProperty(name="Plaza Thickness", default=0.04, min=0.0, description="Raised plaza slab thickness")
    plaza_color: FloatVectorProperty(name="Plaza Color", subtype='COLOR', size=4, default=(0.23,0.23,0.25,1.0))

    # Streets
    make_street_mesh: BoolProperty(name="Create Street Mesh", default=True)
    city_street_width: FloatProperty(name="Street Width (×cell)", default=0.6, min=0.2, max=1.2)
    city_street_height: FloatProperty(name="Street Thickness", default=0.04, min=0.0)
    city_street_color: FloatVectorProperty(name="Street Color", subtype='COLOR', size=4, default=(0.12,0.12,0.12,1.0))

    # Lot subdivision & façade variability
    lot_min_cells: IntProperty(name="Lot Min (cells)", default=2, min=1, soft_max=8, description="Minimum lot width/height in cell units")
    lot_max_cells: IntProperty(name="Lot Max (cells)", default=4, min=1, soft_max=12, description="Maximum lot width/height in cell units")
    lot_gap: FloatProperty(name="Lot Gap (m)", default=0.35, min=0.0, soft_max=1.5, description="Spacing between lots inside a block")

    podium_height: FloatProperty(name="Podium Height", default=3.2, min=0.0, soft_max=12.0)
    # Variable podium footprint
    podium_min_frac: FloatProperty(name="Podium Min % of Lot", default=0.80, min=0.3, max=1.0)
    podium_max_frac: FloatProperty(name="Podium Max % of Lot", default=1.00, min=0.3, max=1.0)
    # Variable tower footprint
    tower_min_frac: FloatProperty(name="Tower Min % of Lot", default=0.45, min=0.2, max=1.0)
    tower_max_frac: FloatProperty(name="Tower Max % of Lot", default=0.85, min=0.2, max=1.0)

    # Tower heights
    city_height_min: FloatProperty(name="Tower H min", default=8.0, min=0.5)
    city_height_max: FloatProperty(name="Tower H max", default=32.0, min=0.5)

    # Districts (colors)
    district_count: IntProperty(name="Districts", default=3, min=1, max=4)
    district1_color: FloatVectorProperty(name="District 1", subtype='COLOR', size=4, default=(0.85,0.55,0.55,1))
    district2_color: FloatVectorProperty(name="District 2", subtype='COLOR', size=4, default=(0.55,0.85,0.65,1))
    district3_color: FloatVectorProperty(name="District 3", subtype='COLOR', size=4, default=(0.55,0.65,0.95,1))
    district4_color: FloatVectorProperty(name="District 4", subtype='COLOR', size=4, default=(0.90,0.80,0.55,1))

    # Roofs
    roof_flat_prob: FloatProperty(name="Flat %", default=0.45, min=0.0, max=1.0)
    roof_gx_prob:   FloatProperty(name="Gable X %", default=0.22, min=0.0, max=1.0)
    roof_gy_prob:   FloatProperty(name="Gable Y %", default=0.22, min=0.0, max=1.0)
    roof_hip_prob:  FloatProperty(name="Hip %",  default=0.11, min=0.0, max=1.0)
    roof_height:    FloatProperty(name="Roof Height", default=0.6, min=0.0, max=3.0)
    roof_color:     FloatVectorProperty(name="Roof Color", subtype='COLOR', size=4, default=(0.20,0.20,0.22,1))

# ──────────────────────────────────────────────────────────────────────────────
# Operators
# ──────────────────────────────────────────────────────────────────────────────
class MMM_OT_Generate(Operator):
    bl_idname = "mmm.generate"
    bl_label = "Generate Maze/City"
    bl_description = "Generate walls+floor (Maze) or city blocks+streets+plazas with districts, variable footprints, and roofs."

    def execute(self, context):
        p = context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)

        # Prepare collections
        maze_col = get_collection("maze")
        paths_col = get_collection("maze_paths")
        clear_collection(maze_col)
        clear_collection(paths_col)

        plaza_cells=set()
        if p.use_city_mode:
            bitmap, H, W, s_open, e_open = city_network(
                p.rows, p.cols, rng,
                jitter=p.city_grid_jitter, loop_ratio=p.city_loop_ratio,
                cul_p=p.city_culdesac_prob, cul_len=p.city_culdesac_len,
                plaza_p=p.city_plaza_prob, plaza_edge=p.city_plaza_minmax,
                plaza_out_set=plaza_cells
            )
        else:
            bitmap, H, W, s_open, e_open = prims_maze(p.rows, p.cols, rng)

            # Add a few loops but preserve dead-ends
            def count_passages_and_deadends(grid):
                rows, cols = len(grid), len(grid[0])
                passages=0; dead=0
                for r in range(1,rows-1):
                    for c in range(1,cols-1):
                        if not grid[r][c]:
                            passages+=1; deg=0
                            for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
                                rr,cc=r+dr,c+dc
                                if 0<=rr<rows and 0<=cc<cols and not grid[rr][cc]: deg+=1
                            if deg==1: dead+=1
                return passages, dead

            def carve_loops_with_deadend_guard(grid, H, W, rng, ratio=0.06, min_deadend_ratio=0.06, min_deadend_abs=6):
                if ratio<=0: return
                cand=[]
                for r in range(1,H-1):
                    for c in range(1,W-1):
                        if grid[r][c]:
                            if r%2==1 and c%2==0 and (not grid[r][c-1]) and (not grid[r][c+1]): cand.append((r,c))
                            if r%2==0 and c%2==1 and (not grid[r-1][c]) and (not grid[r+1][c]): cand.append((r,c))
                rng.shuffle(cand)
                max_to=int(len(cand)*ratio)
                total,_ = count_passages_and_deadends(grid)
                min_dead = max(min_deadend_abs, math.ceil(total*min_deadend_ratio))
                carved=0
                for (r,c) in cand:
                    if carved>=max_to: break
                    grid[r][c]=False
                    _, dead_after = count_passages_and_deadends(grid)
                    if dead_after>=min_dead: carved+=1
                    else: grid[r][c]=True

            carve_loops_with_deadend_guard(bitmap, H, W, rng)

        # Start/End (nudged inside)
        start = inward(s_open, H, W)
        end   = inward(e_open,   H, W)

        # World transforms
        total_w, total_h = W*p.cell_w, H*p.cell_h
        off_x, off_y = -total_w/2 + p.cell_w/2, -total_h/2 + p.cell_h/2

        maze_target = get_collection("maze")

        if p.use_city_mode:
            # Streets visual
            if p.make_street_mesh:
                build_street_ribbons(bitmap, H, W, p.cell_w, p.cell_h, off_x, off_y,
                                     p.city_street_width, p.city_street_height, tuple(p.city_street_color), maze_target)
            # Blocks → subdivide to lots → podium+tower with variable footprints
            blocks = merge_rectangles(bitmap, H, W)
            district_colors = [tuple(p.district1_color), tuple(p.district2_color),
                               tuple(p.district3_color), tuple(p.district4_color)]
            roof_probs = {"FLAT":p.roof_flat_prob, "GABLE_X":p.roof_gx_prob,
                          "GABLE_Y":p.roof_gy_prob, "HIP":p.roof_hip_prob}
            build_city_with_districts(
                blocks_cells=blocks,
                cell_w=p.cell_w, cell_h=p.cell_h, off_x=off_x, off_y=off_y,
                lot_min=p.lot_min_cells, lot_max=p.lot_max_cells, lot_gap=p.lot_gap,
                podium_height=p.podium_height,
                podium_min_frac=p.podium_min_frac, podium_max_frac=p.podium_max_frac,
                tower_min_frac=p.tower_min_frac,   tower_max_frac=p.tower_max_frac,
                hmin=p.city_height_min, hmax=p.city_height_max,
                district_count=max(1, min(4, p.district_count)),
                district_colors=district_colors,
                roof_probs=roof_probs, roof_height=p.roof_height, roof_color=tuple(p.roof_color),
                target_col=maze_target, rng=rng
            )
            # Plazas
            build_plaza_meshes(plaza_cells, p.cell_w, p.cell_h, off_x, off_y, p.plaza_thickness, tuple(p.plaza_color), maze_target)

            # Ground
            if p.make_floor:
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
                floor=bpy.context.active_object; floor.name="CityGround"
                floor.dimensions=(total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
                sit_on_ground(floor)
                fm=ensure_mat(p.floor_mat_name, (0.10,0.10,0.11,1))
                if floor.data.materials: floor.data.materials[0]=fm
                else: floor.data.materials.append(fm)
                link_exclusive(floor, maze_target)
        else:
            # Classic maze walls
            blocks = merge_rectangles(bitmap, H, W)
            rects=[]; heights=[]
            for (r,c,h,w) in blocks:
                sx=w*p.cell_w; sy=h*p.cell_h
                cx = off_x + c*p.cell_w + (w-1)*p.cell_w/2
                cy = -(off_y + r*p.cell_h + (h-1)*p.cell_h/2)
                x0, x1 = cx - sx/2, cx + sx/2
                y0, y1 = cy - sy/2, cy + sy/2
                rects.append((x0,x1,y0,y1))
                heights.append(p.height_max if p.uniform_height else random.uniform(p.height_min, p.height_max))
            build_batched_prisms("MazeWalls", rects, heights, tuple(p.wall_color), maze_target)
            if p.make_floor:
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
                floor=bpy.context.active_object; floor.name="MazeFloor"
                floor.dimensions=(total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
                sit_on_ground(floor)
                fm=ensure_mat(p.floor_mat_name, (0.14,0.14,0.16,1))
                if floor.data.materials: floor.data.materials[0]=fm
                else: floor.data.materials.append(fm)
                link_exclusive(floor, maze_target)

        # Cache for path builder
        clr = clearance_score(bitmap)
        graph = build_corridor_graph(bitmap, start, end)
        cache=_default_cache()
        cache.update({
            "bitmap": copy.deepcopy(bitmap), "rows": H, "cols": W,
            "start": start, "end": end, "off_x": off_x, "off_y": off_y,
            "cell_w": p.cell_w, "cell_h": p.cell_h, "paths": [],
            "clearance": clr, "graph": graph, "metrics": [], "metrics_summary": {},
            "plaza_cells": set(plaza_cells),
        })
        set_cache(context.scene, cache)

        kind = "City" if p.use_city_mode else "Maze"
        self.report({'INFO'}, f"{kind} {H}x{W} generated. Build Path Tiles when ready.")
        return {'FINISHED'}

class MMM_OT_BuildPaths(Operator):
    bl_idname = "mmm.build_paths"
    bl_label = "Build Path Tiles (All Enabled)"
    bl_description = "Generate colored floor tiles for all enabled styles. Enforces uniqueness and intersection bounds."

    def execute(self, context):
        p = context.scene.mmm_props

        cache = get_cache(context.scene)
        if not cache or not cache.get("bitmap"):
            cache = MODULE_CACHE.get("__last__")  # fallback for City Mode/odd contexts
        if not cache or not cache.get("bitmap"):
            self.report({'WARNING'}, "Generate a maze/city first.")
            return {'CANCELLED'}

        prefs=bpy.context.preferences
        prev_undo=prefs.edit.use_global_undo; prefs.edit.use_global_undo=False
        prev_lock=bpy.context.scene.render.use_lock_interface; bpy.context.scene.render.use_lock_interface=True
        try:
            bitmap=cache["bitmap"]; start,end=tuple(cache["start"]),tuple(cache["end"])
            off_x,off_y=cache["off_x"],cache["off_y"]
            cell_w,cell_h=cache["cell_w"],cache["cell_h"]
            clr=cache.get("clearance"); graph=cache.get("graph")
            use_graph=True if (p.use_graph_accel and graph) else False

            styles=[]
            if p.use_purist:       styles.append(("PURIST","DIJK", dict(step=1.0, turn=0.0, alley=0.0), tuple(p.col_purist)))
            if p.use_smooth:       styles.append(("SMOOTH","DIJK", dict(step=1.0, turn=0.9, alley=0.0), tuple(p.col_smooth)))
            if p.use_explorative: styles.append(("EXPLORATIVE","MEAN", dict(bias_turn=0.6, bias_open=0.6, bias_goal=-0.6), tuple(p.col_explorative)))
            if p.use_zigzag:       styles.append(("ZIGZAG","MEAN", dict(bias_turn=1.2, bias_open=0.0, bias_goal=-0.4), tuple(p.col_zigzag)))
            if not styles:
                self.report({'WARNING'},"No styles enabled."); return {'CANCELLED'}

            rng=random.Random(None if p.randomize else p.seed)
            paths_col=get_collection("maze_paths")
            has_existing = isinstance(cache.get("paths"), list) and bool(cache["paths"])
            append = bool(p.append_paths and has_existing)
            existing = list(cache.get("paths", []))
            if not append:
                clear_collection(paths_col)
                existing=[]; cache["paths"]=[]

            # Start tile (one)
            if (not append) or (not any(o.name=="StartTile" for o in paths_col.objects)):
                sx,sy=rc_to_world(off_x,off_y,cell_w,cell_h,start)
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sx,sy,0.0))
                st=bpy.context.active_object; st.name="StartTile"
                st.dimensions=(p.tile_size,p.tile_size,p.tile_height)
                sit_on_ground(st); st.location.z += p.tile_z_offset
                sm=ensure_mat("StartColor", tuple(p.start_color))
                if st.data.materials: st.data.materials[0]=sm
                else: st.data.materials.append(sm)
                link_exclusive(st, paths_col)

            trials = p.explorative_trials if not p.fast_mode else max(100, p.explorative_trials//4)
            reroutes = p.unique_reroute_tries if not p.fast_mode else max(2, p.unique_reroute_tries//2)

            if use_graph:
                nodes=graph["nodes"]; idx_of={rc:i for i,rc in enumerate(nodes)}
                si=idx_of.get(start); ei=idx_of.get(end)
                if si is None or ei is None:
                    use_graph=False

            built=0; new_entries=[]; per_metrics_now=[]
            def simple_route_graph(name):
                if name=="PURIST": return graph_shortest(graph, si, ei)
                if name=="SMOOTH": return graph_smooth_turnaware(graph, si, ei, tau=0.9)
                if name=="EXPLORATIVE": return graph_meander_long(graph, si, ei, rng, trials=trials)
                if name=="ZIGZAG": return graph_zigzaggy(graph, si, ei, rng, trials=max(150,trials//2))
                return []

            def try_build_named(name, solver, params, color):
                nonlocal built, existing, new_entries
                def attempt_one():
                    if use_graph:
                        if p.enforce_unique:
                            if name=="PURIST":
                                return ensure_unique_route_graph_shortest(graph, si, ei, existing, start, end, rng, max_tries=reroutes, thresh=p.unique_jaccard_max)
                            elif name=="SMOOTH":
                                return ensure_unique_route_graph_smooth(graph, si, ei, tau=0.9, existing=existing, start=start, end=end, rng=rng, max_tries=reroutes, thresh=p.unique_jaccard_max)
                            elif name=="EXPLORATIVE":
                                return ensure_unique_route_graph_meander(graph, si, ei, rng, trials=trials, existing=existing, thresh=p.unique_jaccard_max, max_tries=reroutes)
                            else:
                                return ensure_unique_route_graph_zigzag(graph, si, ei, rng, trials=max(150,trials//2), existing=existing, thresh=p.unique_jaccard_max, max_tries=reroutes)
                        else:
                            return simple_route_graph(name)
                    if p.enforce_unique:
                        if solver=="DIJK":
                            return ensure_unique_route(bitmap, start, end, params, existing, rng, max_tries=reroutes, thresh=p.unique_jaccard_max, clr=clr)
                        else:
                            return ensure_unique_route_meander(bitmap, start, end, rng, trials, existing, start_bias=params, thresh=p.unique_jaccard_max, max_tries=reroutes, clr=clr)
                    else:
                        return simple_route_grid(bitmap, start, end, solver, params, rng, trials, clr)

                t_s=time.perf_counter()
                route=attempt_one()
                if not route and use_graph:
                    route = simple_route_grid(bitmap, start, end, solver, params, rng, trials, clr)
                t_e=time.perf_counter()
                if not route:
                    return

                if p.enforce_overlap and existing:
                    ok=overlap_ok(route, existing, p.min_shared_frac, p.max_shared_frac)
                    tries=reroutes
                    while (not ok) and tries>0:
                        tries-=1
                        worst_ent=None; best=0.0
                        for ent in existing:
                            f=_shared_fraction(route, ent["cells"])
                            if f>best: best=f; worst_ent=ent
                        forbid_pool = list(set(map(tuple,route[1:-1])) & set(map(tuple,worst_ent["cells"][1:-1]))) if worst_ent else []
                        forbid=set(random.sample(forbid_pool, max(1,int(0.2*len(forbid_pool))))) if forbid_pool else set()
                        if solver=="DIJK":
                            route=dijkstra_cost(bitmap, start, end, params, forbidden=forbid, clr=clr)
                        else:
                            route=greedy_meander(bitmap, start, end, rng, max(50,trials//2),
                                                 bias_turn=params.get("bias_turn",0.0),
                                                 bias_open=params.get("bias_open",0.0),
                                                 bias_goal=params.get("bias_goal",-0.7),
                                                 forbidden=forbid, clr=clr)
                        if not route:
                            route=attempt_one()
                        ok = bool(route) and overlap_ok(route, existing, p.min_shared_frac, p.max_shared_frac)
                    if not route or not ok:
                        return

                tag = f"{name}#{sum(1 for e in (existing+new_entries) if e['key'].startswith(name))+1}" if p.append_paths and cache["paths"] else name
                entry={"key":tag, "cells":[tuple(rc) for rc in route], "color": color}
                new_entries.append(entry); existing.append(entry); built+=1
                per_metrics_now.append({"key":tag,"len":len(route),"turns":_count_turns_on_cells(route),"ms":round((t_e-t_s)*1000.0,2),"graph":bool(use_graph)})

            for (name, solver, params, color) in styles:
                try_build_named(name, solver, params, color)

            cache["paths"]=list(existing); set_cache(context.scene, cache)

            # Draw tiles and intersections
            clear_collection(get_collection("maze_paths"), name_prefixes=("Path_","Path_Intersections"))
            counts=Counter()
            for ent in cache["paths"]:
                for rc in ent["cells"]: counts[tuple(rc)]+=1
            overlap_cells={rc for rc,n in counts.items() if n>=2}
            geom=(cell_w,cell_h,off_x,off_y,p.tile_size,p.tile_height,p.tile_z_offset)
            for ent in cache["paths"]:
                draw_tiles_for_path(f"Path_{ent['key']}", ent["cells"], ent["color"], geom, skip_cells=overlap_cells)
            if overlap_cells:
                draw_tiles_for_cells("Path_Intersections", overlap_cells, tuple(p.col_intersection), geom)

            # Metrics
            metrics_map={m["key"]:m for m in per_metrics_now}
            all_metrics=[]
            for ent in cache["paths"]:
                k=ent["key"]
                if k in metrics_map: all_metrics.append(metrics_map[k])
                else: all_metrics.append({"key":k,"len":len(ent["cells"]), "turns":_count_turns_on_cells(ent["cells"]), "ms":None, "graph":bool(use_graph)})
            ms_total=round((sum(m.get("ms",0) or 0 for m in per_metrics_now)),2)
            cache["metrics"]=all_metrics
            cache["metrics_summary"]={"total_paths":len(cache["paths"]), "intersections":len(overlap_cells), "ms_total":ms_total, "graph_used":bool(use_graph)}
            set_cache(context.scene, cache)

            self.report({'INFO'}, f"Built {len(new_entries)} new path(s). Total: {len(cache['paths'])}. Intersections: {len(overlap_cells)}")
            return {'FINISHED'}
        finally:
            prefs.edit.use_global_undo = prev_undo
            bpy.context.scene.render.use_lock_interface = prev_lock

class MMM_OT_ClearPaths(Operator):
    bl_idname="mmm.clear_paths"
    bl_label="Clear Paths Only"
    def execute(self, context):
        clear_collection(get_collection("maze_paths"))
        cache=get_cache(context.scene) or _default_cache()
        cache["paths"]=[]; cache["metrics"]=[]; cache["metrics_summary"]={}
        set_cache(context.scene, cache)
        self.report({'INFO'},"Cleared path overlays & cache.")
        return {'FINISHED'}

class MMM_OT_Export(Operator):
    bl_idname="mmm.export"
    bl_label="Export (OBJ/FBX/GLB)"
    export_format: EnumProperty(
        name="Format",
        items=[('OBJ',"OBJ","Wavefront OBJ"),('FBX',"FBX","Autodesk FBX"),('GLB',"GLB","glTF Binary")],
        default='GLB'
    )
    include_paths: BoolProperty(name="Include Paths", default=True)
    join_mode: EnumProperty(
        name="Mode",
        items=[('SEPARATE',"Separate Objects","Export each mesh separately"),
               ('MERGED',"Single Mesh","Export a temporary joined mesh")],
        default='SEPARATE'
    )
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')

    def invoke(self, context, event):
        ext={'OBJ':".obj",'FBX':".fbx",'GLB':".glb"}[self.export_format]
        if not self.filepath: self.filepath=bpy.path.abspath(f"//maze{ext}")
        context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}

    def execute(self, context):
        def select_only(objs):
            bpy.ops.object.select_all(action='DESELECT')
            for o in objs:
                try:o.select_set(True)
                except: pass
            if objs: bpy.context.view_layer.objects.active = objs[0]

        objs=[]
        maze_col=get_collection("maze"); objs += [o for o in maze_col.objects if o.type=='MESH']
        if self.include_paths:
            paths_col=get_collection("maze_paths"); objs += [o for o in paths_col.objects if o.type=='MESH']
        if not objs:
            self.report({'WARNING'},"Nothing to export."); return {'CANCELLED'}

        temp=None; export_set=objs
        if self.join_mode=='MERGED':
            select_only(objs); bpy.ops.object.duplicate()
            dups=[o for o in bpy.context.view_layer.objects if o.select_get()]
            if not dups: self.report({'WARNING'}, "Duplication failed."); return {'CANCELLED'}
            bpy.context.view_layer.objects.active=dups[0]
            try: bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            except: pass
            bpy.ops.object.join(); temp=bpy.context.view_layer.objects.active
            temp.name="MazeExport_Temp"; link_exclusive(temp, maze_col); export_set=[temp]

        select_only(export_set)
        fp=bpy.path.abspath(self.filepath); os.makedirs(os.path.dirname(fp), exist_ok=True)
        try:
            if self.export_format=='OBJ': bpy.ops.wm.obj_export(filepath=fp, export_selected_objects=True)
            elif self.export_format=='FBX': bpy.ops.export_scene.fbx(filepath=fp, use_selection=True, apply_scale_options='FBX_SCALE_NONE')
            elif self.export_format=='GLB': bpy.ops.export_scene.gltf(filepath=fp, export_format='GLB', use_selection=True)
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            if temp:
                select_only([temp]); bpy.ops.object.delete()
            return {'CANCELLED'}
        if temp:
            select_only([temp]); bpy.ops.object.delete()
        self.report({'INFO'}, f"Exported to {fp}")
        return {'FINISHED'}

# ──────────────────────────────────────────────────────────────────────────────
# UI Panels
# ──────────────────────────────────────────────────────────────────────────────
class MMM_PT_Main(Panel):
    bl_label="Mo's Maze Maker"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category="Mo's Maze Maker"

    def draw(self, context):
        p=context.scene.mmm_props; L=self.layout

        # City Mode
        box=L.box(); box.label(text="City Mode (Blocks & Streets)", icon='COMMUNITY')
        box.prop(p,"use_city_mode")
        col=box.column(align=True); col.enabled=p.use_city_mode
        row=col.row(align=True); row.prop(p,"city_grid_jitter"); row.prop(p,"city_loop_ratio")
        row=col.row(align=True); row.prop(p,"city_culdesac_prob"); row.prop(p,"city_culdesac_len")
        row=col.row(align=True); row.prop(p,"city_plaza_prob"); row.prop(p,"city_plaza_minmax")
        row=col.row(align=True); row.prop(p,"plaza_thickness"); row.prop(p,"plaza_color")
        row=col.row(align=True); row.prop(p,"make_street_mesh"); row.prop(p,"city_street_width")
        row=col.row(align=True); row.prop(p,"city_street_height"); row.prop(p,"city_street_color")

        # Districts + façade + roofs
        col2=box.column(align=True); col2.enabled=p.use_city_mode
        col2.label(text="Districts & Façade Variability", icon='COLOR')
        row=col2.row(align=True); row.prop(p,"district_count")
        row=col2.row(align=True); row.prop(p,"district1_color"); row.prop(p,"district2_color")
        row=col2.row(align=True); row.prop(p,"district3_color"); row.prop(p,"district4_color")
        row=col2.row(align=True); row.prop(p,"podium_height")
        row=col2.row(align=True); row.prop(p,"podium_min_frac"); row.prop(p,"podium_max_frac")
        row=col2.row(align=True); row.prop(p,"tower_min_frac");  row.prop(p,"tower_max_frac")
        row=col2.row(align=True); row.prop(p,"city_height_min"); row.prop(p,"city_height_max")
        col2.label(text="Roofs", icon='MOD_CLOTH')
        row=col2.row(align=True); row.prop(p,"roof_flat_prob"); row.prop(p,"roof_gx_prob")
        row=col2.row(align=True); row.prop(p,"roof_gy_prob");  row.prop(p,"roof_hip_prob")
        row=col2.row(align=True); row.prop(p,"roof_height");   row.prop(p,"roof_color")

        # Maze Size & Randomness
        box=L.box(); box.label(text="Maze Size & Randomness — Prim's", icon='MESH_GRID')
        row=box.row(align=True); row.prop(p,"rows"); row.prop(p,"cols")
        row=box.row(align=True); row.prop(p,"randomize"); 
        if not p.randomize: row.prop(p,"seed")

        # Geometry & Floor
        box=L.box(); box.label(text="Geometry & Floor", icon='MOD_SOLIDIFY')
        row=box.row(align=True); row.prop(p,"cell_w"); row.prop(p,"cell_h")
        row=box.row(align=True); row.prop(p,"height_min"); row.prop(p,"height_max")
        box.prop(p,"uniform_height")
        row=box.row(align=True); row.prop(p,"make_floor"); row.prop(p,"floor_thickness")

        # Materials (classic maze)
        box=L.box(); box.label(text="Materials", icon='MATERIAL')
        row=box.row(align=True); row.prop(p,"wall_color"); row.prop(p,"wall_mat_name")
        box.prop(p,"floor_mat_name")

        L.operator("mmm.generate", icon='MESH_CUBE', text="Generate Maze/City")

        L.separator()

        # Tiles & colors
        box=L.box(); box.label(text="Path Tiles & Colors", icon='EVENT_T')
        row=box.row(align=True); row.prop(p,"tile_size"); row.prop(p,"tile_height"); row.prop(p,"tile_z_offset")
        row=box.row(align=True); row.prop(p,"start_color"); row.prop(p,"col_intersection")

        # Styles
        box=L.box(); box.label(text="Path Styles (4)", icon='IPO_BEZIER')
        row=box.row(align=True); row.prop(p,"use_purist");      row.prop(p,"col_purist")
        row=box.row(align=True); row.prop(p,"use_smooth");      row.prop(p,"col_smooth")
        row=box.row(align=True); row.prop(p,"use_explorative");row.prop(p,"col_explorative")
        row=box.row(align=True); row.prop(p,"use_zigzag");      row.prop(p,"col_zigzag")
        box.prop(p,"explorative_trials")

        # Uniqueness & Intersections
        box=L.box(); box.label(text="Uniqueness Guard", icon='MOD_PHYSICS')
        row=box.row(align=True); row.prop(p,"enforce_unique"); row.prop(p,"unique_jaccard_max")
        row=box.row(align=True); row.prop(p,"unique_reroute_tries")

        box=L.box(); box.label(text="Intersection Control", icon='OVERLAY')
        row=box.row(align=True); row.prop(p,"enforce_overlap")
        row=box.row(align=True); row.prop(p,"min_shared_frac"); row.prop(p,"max_shared_frac")

        # Performance & Build
        box=L.box(); box.label(text="Performance & Build", icon='SORTTIME')
        row=box.row(align=True); row.prop(p,"use_graph_accel"); row.prop(p,"fast_mode")
        cache=get_cache(context.scene, read_only=True)
        if bool(cache.get("paths")):
            row=box.row(align=True); row.prop(p,"append_paths")
        L.operator("mmm.build_paths", icon='MOD_BUILD', text="Build Path Tiles (All Enabled)")
        L.operator("mmm.clear_paths", icon='TRASH', text="Clear Paths Only")

        # Export
        box=L.box(); box.label(text="Export", icon='EXPORT')
        box.operator("mmm.export", icon='EXPORT', text="Export (OBJ/FBX/GLB)")

class MMM_PT_Metrics(Panel):
    bl_label="Mo's Maze Maker — Metrics"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category="Mo's Maze Maker"
    def draw(self, context):
        L=self.layout
        cache=get_cache(context.scene, read_only=True)
        paths=cache.get("paths") or []
        metrics=cache.get("metrics") or []
        summary=cache.get("metrics_summary") or {}
        if not paths:
            L.label(text="No path data yet. Build Path Tiles first.", icon='INFO'); return
        box=L.box(); box.label(text="Summary", icon='INFO')
        row=box.row(align=True); row.label(text=f"Total paths: {summary.get('total_paths','–')}"); row.label(text=f"Intersections: {summary.get('intersections','–')}")
        row=box.row(align=True); row.label(text=f"Build time: {summary.get('ms_total','–')} ms"); row.label(text=f"Graph Accel: {'ON' if summary.get('graph_used') else 'OFF'}")
        box=L.box(); box.label(text="Per-Path", icon='SEQ_LUMA_WAVEFORM')
        for m in metrics:
            row=box.row(align=True)
            row.label(text=f"{m.get('key','?')}")
            row.label(text=f"Len: {m.get('len','–')}")
            row.label(text=f"Turns: {m.get('turns','–')}")
            row.label(text=f"Solver: {'Graph' if m.get('graph',False) else 'Grid'}")
            ms=m.get("ms"); row.label(text=("Time: {:.2f} ms".format(ms)) if ms is not None else "Time: —")

# ──────────────────────────────────────────────────────────────────────────────
# Register
# ──────────────────────────────────────────────────────────────────────────────
classes=(MMM_Props, MMM_OT_Generate, MMM_OT_BuildPaths, MMM_OT_ClearPaths, MMM_OT_Export, MMM_PT_Main, MMM_PT_Metrics)
def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.mmm_props = PointerProperty(type=MMM_Props)
def unregister():
    del bpy.types.Scene.mmm_props
    for c in reversed(classes): bpy.utils.unregister_class(c)
if __name__=="__main__":
    register()

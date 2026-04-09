bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G's brains (plus ChatGPT brawn)",
    "version": (2, 6, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A maze generator exploring parsimony.",
    "category": "Add Mesh",
}

import bpy, random, math, os, copy, time
from mathutils import Vector
from collections import deque, Counter
from heapq import heappush, heappop
from bpy.props import (IntProperty, FloatProperty, BoolProperty, FloatVectorProperty,
                       PointerProperty, StringProperty, EnumProperty)
from bpy.types import Operator, Panel, PropertyGroup

# ========= Module Runtime Cache (not stored on Scene) =========
MODULE_CACHE = {}

def _default_cache():
    return {
        "bitmap": None,
        "rows": 0, "cols": 0,
        "start": None, "end": None,
        "off_x": 0.0, "off_y": 0.0,
        "cell_w": 1.0, "cell_h": 1.0,
        "paths": [],        # list of {"key","cells","color"}
        "clearance": None,  # precomputed clearance field
        "graph": None,      # corridor graph (nodes/adj)
        "metrics": [],      # list of {key,len,turns,ms,graph}
        "metrics_summary": {} # {total_paths, intersections, ms_total, graph_used}
    }

def get_cache(scene, read_only=False):
    key = scene.as_pointer()
    data = MODULE_CACHE.get(key)
    if data is None:
        return _default_cache() if read_only else None
    return data

def set_cache(scene, data):
    MODULE_CACHE[scene.as_pointer()] = data

# ===================== Small utils =====================
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
        m = bpy.data.materials.new(name=name); m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = rgba
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m

def sit_on_ground(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    o_eval = obj.evaluated_get(dg)
    bb = [o_eval.matrix_world @ Vector(c) for c in o_eval.bound_box]
    min_z = min(v.z for v in bb); obj.location.z -= min_z

def rc_to_world(off_x, off_y, cell_w, cell_h, rc):
    r,c=rc; return off_x + c*cell_w, -(off_y + r*cell_h)

# ===================== Maze (Prim's) =====================
# bitmap: True=wall, False=passage
def prims_maze(rows, cols, rng):
    H, W = rows*2+1, cols*2+1
    g = [[True]*W for _ in range(H)]
    sr, sc = rng.randrange(rows), rng.randrange(cols)
    r, c = sr*2+1, sc*2+1
    g[r][c] = False
    front=[]
    def push(r,c):
        for dr,dc in ((-2,0),(2,0),(0,-2),(0,2)):
            rr,cc=r+dr,c+dc
            if 1<=rr<H-1 and 1<=cc<W-1 and g[rr][cc]:
                front.append(((rr,cc),(r+dr//2,c+dc//2)))
    push(r,c)
    while front:
        i=rng.randrange(len(front))
        (rr,cc),(wr,wc)=front.pop(i)
        if g[rr][cc]:
            g[wr][wc]=False; g[rr][cc]=False; push(rr,cc)
    start=end=None
    for r in range(1,H-1):
        if not g[r][1]: g[r][0]=False; start=(r,0); break
    for r in range(H-2,0,-1):
        if not g[r][W-2]: g[r][W-1]=False; end=(r,W-1); break
    return g, H, W, start, end

def inward(rc, rows, cols):
    r,c=rc
    if r==0: return (1,c)
    if r==rows-1: return (rows-2,c)
    if c==0: return (r,1)
    if c==cols-1: return (r,cols-2)
    return rc

def merge_rectangles(grid, rows, cols):
    g=[row[:] for row in grid]
    blocks=[]
    for r in range(rows):
        c=0
        while c<cols:
            if not g[r][c]:
                c+=1; continue
            w=1
            while c+w<cols and g[r][c+w]: w+=1
            h=1
            while r+h<rows and all(g[r+h][cc] for cc in range(c,c+w)): h+=1
            for rr in range(r,r+h):
                for cc in range(c,c+w): g[rr][cc]=False
            blocks.append((r,c,h,w)); c+=w
    return blocks

# ===================== Grid helpers =====================
def neighbors_passages(g, r, c):
    R,C=len(g),len(g[0])
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr,cc=r+dr,c+dc
        if 0<=rr<R and 0<=cc<C and not g[rr][cc]:
            yield rr,cc,dr,dc

def clearance_score(g):
    R,C=len(g),len(g[0])
    s=[[0]*C for _ in range(R)]
    for r in range(R):
        for c in range(C):
            if g[r][c]: continue
            walls=0
            for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
                rr,cc=r+dr,c+dc
                if 0<=rr<R and 0<=cc<C and g[rr][cc]: walls+=1
            s[r][c]=walls  # 0 open, 4 tight
    return s

def manhattan(a,b): return abs(a[0]-b[0])+abs(a[1]-b[1])

# ===================== Turn-aware A* on grid (kept name) =====================
def dijkstra_cost(g, start, goal, params, forbidden=None, clr=None):
    """
    A* with turn-aware heuristic:
    - cost = step + tau*turn + alley*tightness
    - heuristic = Manhattan + small turn bias
    """
    R,C=len(g),len(g[0])
    if clr is None:
        clr = clearance_score(g)
    forbidden = forbidden or set()
    step=params.get('step',1.0); tau=params.get('turn',0.0); alley=params.get('alley',0.0)
    INF=10**12; dist={}; prev={}; pq=[]
    s=(start[0],start[1],(0,0))
    dist[s]=0.0
    def h(r,c,pi):
        return manhattan((r,c), goal) + (0.25 if pi!=(0,0) else 0.0)
    heappush(pq,(h(start[0],start[1],(0,0)), 0.0, s))
    def w_cost(pi,drdc,rr,cc):
        turn = tau if (pi!=(0,0) and pi!=drdc) else 0.0
        tight = clr[rr][cc]/4.0
        return max(0.0, step + turn + alley*tight)
    while pq:
        f, g_cost, st = heappop(pq)
        if g_cost!=dist.get(st,INF): continue
        r,c,pi=st
        if (r,c)==goal:
            path=[]; cur=st
            while cur in prev:
                (rr,cc,_), p = cur, prev[cur]
                path.append((rr,cc)); cur=p
            (rr,cc,_)=cur; path.append((rr,cc)); return path[::-1]
        for rr,cc,dr,dc in neighbors_passages(g,r,c):
            if (rr,cc) in forbidden: continue
            wc=w_cost(pi,(dr,dc),rr,cc); ng=g_cost+wc
            ns=(rr,cc,(dr,dc))
            if ng<dist.get(ns,INF):
                dist[ns]=ng; prev[ns]=st
                heappush(pq,(ng + h(rr,cc,(dr,dc)), ng, ns))
    return []

# ===================== Greedy meander on grid (long, self-avoiding) =====================
def greedy_meander(g, start, goal, rng, trials, bias_turn=0.0, bias_open=0.0, bias_goal=-0.7, forbidden=None, clr=None):
    """Long simple path with reachability guard. bias_turn>0 favors turns; bias_open>0 favors open cells; bias_goal negative pushes away from goal early."""
    forbidden = forbidden or set()
    if clr is None:
        clr = clearance_score(g)
    R,C=len(g),len(g[0])
    def reachable(snode, blocked):
        if snode in blocked or goal in blocked: return False
        Q=deque([snode]); seen={snode}
        while Q:
            v=Q.popleft()
            if v==goal: return True
            r,c=v
            for rr,cc,_,_ in neighbors_passages(g,r,c):
                if (rr,cc) not in seen and (rr,cc) not in blocked and (rr,cc) not in forbidden:
                    seen.add((rr,cc)); Q.append((rr,cc))
        return False
    best=None
    for _ in range(trials):
        path=[start]; visited={start}; prev_dir=None
        while path[-1]!=goal:
            r,c=path[-1]; cand=[]
            for rr,cc,dr,dc in neighbors_passages(g,r,c):
                if (rr,cc) in visited or (rr,cc) in forbidden: continue
                blocked=visited.copy(); blocked.add((rr,cc))
                if not reachable((rr,cc), blocked - {(rr,cc)}): continue
                turn = 1.0 if (prev_dir is not None and prev_dir!=(dr,dc)) else 0.0
                open_bonus = 1.0 - (clr[rr][cc]/4.0)
                dgoal = manhattan((rr,cc), goal)
                score = (+bias_turn*turn) + (+bias_open*open_bonus) + (bias_goal*dgoal) + random.random()*0.05
                cand.append(((rr,cc,dr,dc), score))
            if not cand: break
            cand.sort(key=lambda x:x[1], reverse=True)
            pick = random.choice(cand[:min(3,len(cand))])[0]
            rr,cc,dr,dc=pick
            prev_dir=(dr,dc); path.append((rr,cc)); visited.add((rr,cc))
        if path and path[-1]==goal and ((best is None) or (len(path)>len(best))):
            best=path
    return best or []

# ===================== Corridor Graph =====================
# Compress maze into nodes (junctions/ends) + edges (straight runs).
# Graph:
#   graph["nodes"] = [ (r,c), ... ]
#   graph["adj"][i] = [ (j, length, dir, cells) ]  # dir is (dr,dc) from i; cells are the corridor cells in order
def _passage_deg(g, r, c):
    d=0
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr,cc=r+dr,c+dc
        if 0<=rr<len(g) and 0<=cc<len(g[0]) and not g[rr][cc]:
            d+=1
    return d

def build_corridor_graph(g, start, end):
    R,C=len(g),len(g[0])
    is_node = [[False]*C for _ in range(R)]
    nodes = []
    idx_of = {}
    def mark_node(rc):
        if rc not in idx_of:
            idx_of[rc]=len(nodes); nodes.append(rc); is_node[rc[0]][rc[1]]=True

    mark_node(tuple(start)); mark_node(tuple(end))
    for r in range(1,R-1):
        for c in range(1,C-1):
            if not g[r][c]:
                if _passage_deg(g,r,c) != 2:
                    mark_node((r,c))

    adj = {i:[] for i in range(len(nodes))}

    def march(r,c, dr,dc):
        cells = []
        pr,pc = r,c
        while True:
            nr, nc = pr+dr, pc+dc
            if not (0<=nr<R and 0<=nc<C): break
            if g[nr][nc]: break
            cells.append((nr,nc))
            if is_node[nr][nc] or _passage_deg(g,nr,nc)!=2:
                return (nr,nc), cells
            pr,pc = nr,nc
        return None, cells

    for i,(r,c) in enumerate(nodes):
        for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
            rr,cc = r+dr, c+dc
            if 0<=rr<R and 0<=cc<C and not g[rr][cc]:
                end_node, cells = march(r,c, dr,dc)
                if not end_node or not cells: continue
                j = idx_of.get(end_node)
                if j is None: continue
                adj[i].append((j, len(cells), (dr,dc), cells))
                adj[j].append((i, len(cells), (-dr,-dc), list(reversed(cells))))
    return {"nodes": nodes, "adj": adj}

# ---- Graph solvers ----
def _node_heuristic(nodes, A, B):
    return manhattan(nodes[A], nodes[B])

def graph_shortest(graph, start_idx, end_idx):
    nodes, adj = graph["nodes"], graph["adj"]
    INF=10**12
    dist=[INF]*len(nodes); prev=[None]*len(nodes); prev_edge=[None]*len(nodes)
    dist[start_idx]=0
    pq=[(0,start_idx)]
    while pq:
        d,i = heappop(pq)
        if d!=dist[i]: continue
        if i==end_idx: break
        for (j, L, dir_, cells) in adj[i]:
            nd = d + L
            if nd < dist[j]:
                dist[j]=nd; prev[j]=i; prev_edge[j]=(i,j,dir_,cells)
                heappush(pq,(nd,j))
    if dist[end_idx]>=INF: return []
    chain=[]; cur=end_idx
    while cur!=start_idx:
        e = prev_edge[cur]
        if e is None: break
        chain.append(e); cur = prev[cur]
    chain.reverse()
    if not chain: return []
    path_cells=[graph["nodes"][start_idx]]
    for (i,j,dir_,cells) in chain:
        path_cells.extend(cells)
    return path_cells

def graph_smooth_turnaware(graph, start_idx, end_idx, tau=0.9):
    nodes, adj = graph["nodes"], graph["adj"]
    INF=10**12
    start_state=(start_idx,(0,0))
    dist={start_state:0.0}; prev={}; prev_edge={}
    pq=[(0.0, start_state)]
    def turn_cost(prev_dir, new_dir):
        return (tau if (prev_dir!=(0,0) and prev_dir!=new_dir) else 0.0)
    while pq:
        d, st = heappop(pq)
        if d!=dist.get(st,INF): continue
        i, pdir = st
        if i==end_idx:
            chain=[]
            cur=st
            while cur in prev:
                e = prev_edge[cur]; chain.append(e); cur = prev[cur]
            chain.reverse()
            if not chain: return [nodes[start_idx], nodes[end_idx]]
            cells=[nodes[start_idx]]
            for (i,j,dir_,edge_cells) in chain:
                cells.extend(edge_cells)
            return cells
        for (j, L, dir_, cells_edge) in adj[i]:
            nd = d + L + turn_cost(pdir, dir_)
            ns=(j, dir_)
            if nd < dist.get(ns, INF):
                dist[ns]=nd; prev[ns]=st; prev_edge[ns]=(i,j,dir_,cells_edge)
                heappush(pq,(nd, ns))
    return []

def graph_meander_long(graph, start_idx, end_idx, rng, trials=200, bias_turn=0.6, bias_len=0.6, bias_goal=-0.6):
    nodes, adj = graph["nodes"], graph["adj"]
    best=None; best_score=(-1,-1)
    for _ in range(trials):
        path_nodes=[start_idx]; visited={start_idx}; prev_dir=None; tcount=0
        while path_nodes[-1]!=end_idx:
            i = path_nodes[-1]
            cand=[]
            for (j, L, dir_, cells_edge) in adj[i]:
                if j in visited: continue
                if not _graph_reachable(adj, j, end_idx, blocked=visited):
                    continue
                dgoal = _node_heuristic(nodes, j, end_idx)
                turn = 1.0 if (prev_dir is not None and prev_dir!=dir_) else 0.0
                score = (bias_len*L) + (bias_turn*turn) + (bias_goal*dgoal) + rng.random()*0.05
                cand.append((score, j, dir_, L))
            if not cand: break
            cand.sort(key=lambda x:x[0], reverse=True)
            score, j, dir_, L = rng.choice(cand[:min(3,len(cand))])
            if prev_dir is not None and prev_dir!=dir_: tcount += 1
            path_nodes.append(j); visited.add(j); prev_dir=dir_
        if path_nodes and path_nodes[-1]==end_idx:
            cells = _expand_graph_nodepath_to_cells(graph, path_nodes)
            sc = (len(cells), tcount)
            if sc > best_score:
                best = path_nodes; best_score = sc
    if not best: return []
    return _expand_graph_nodepath_to_cells(graph, best)

def graph_zigzaggy(graph, start_idx, end_idx, rng, trials=200):
    nodes, adj = graph["nodes"], graph["adj"]
    best=None; best_score=(-1,-1)
    for _ in range(trials):
        path_nodes=[start_idx]; visited={start_idx}; prev_dir=None; turn_count=0
        while path_nodes[-1]!=end_idx:
            i = path_nodes[-1]
            cand=[]
            for (j, L, dir_, cells_edge) in adj[i]:
                if j in visited: continue
                if not _graph_reachable(adj, j, end_idx, blocked=visited):
                    continue
                turn = 1.0 if (prev_dir is not None and prev_dir!=dir_) else 0.0
                score = (1.2*turn) + (0.1*L) + rng.random()*0.05
                cand.append((score, j, dir_, L))
            if not cand: break
            cand.sort(key=lambda x:x[0], reverse=True)
            score, j, dir_, L = rng.choice(cand[:min(3,len(cand))])
            if prev_dir is not None and prev_dir!=dir_: turn_count += 1
            path_nodes.append(j); visited.add(j); prev_dir=dir_
        if path_nodes and path_nodes[-1]==end_idx:
            cells = _expand_graph_nodepath_to_cells(graph, path_nodes)
            sc = (turn_count, len(cells))
            if sc > best_score:
                best = path_nodes; best_score = sc
    if not best: return []
    return _expand_graph_nodepath_to_cells(graph, best)

def _graph_reachable(adj, src, dst, blocked):
    Q=deque([src]); seen={src} | set(blocked)
    if src in blocked: return False
    while Q:
        i=Q.popleft()
        if i==dst: return True
        for (j, _, _, _) in adj[i]:
            if j not in seen:
                seen.add(j); Q.append(j)
    return False

def _expand_graph_nodepath_to_cells(graph, node_path):
    if not node_path: return []
    cells=[graph["nodes"][node_path[0]]]
    for a,b in zip(node_path, node_path[1:]):
        hit=None
        for (j, L, dir_, edge_cells) in graph["adj"][a]:
            if j==b:
                hit=edge_cells; break
        if not hit: return []
        cells.extend(hit)
    return cells

def _count_turns_on_cells(cells):
    if len(cells)<3: return 0
    turns=0
    def dir_of(a,b): return (b[0]-a[0], b[1]-a[1])
    prev = dir_of(cells[0], cells[1])
    for i in range(1,len(cells)-1):
        d = dir_of(cells[i], cells[i+1])
        if d!=prev: turns+=1
        prev=d
    return turns

# ===================== Uniqueness / similarity / overlap =====================
def jaccard_similarity(A, B, ignore):
    a = set(map(tuple, A)) - ignore
    b = set(map(tuple, B)) - ignore
    if not a and not b: return 1.0
    return len(a & b) / max(1, len(a | b))

def is_too_similar(candidate, existing_entries, start, end, thresh):
    ignore={start,end}
    for ent in existing_entries:
        if jaccard_similarity(candidate, ent["cells"], ignore) >= thresh:
            return True
    return False

def _shared_fraction(candidate_cells, ent_cells):
    # fraction of candidate (ignoring endpoints) that overlaps ent (ignoring endpoints)
    A = set(map(tuple, candidate_cells[1:-1]))
    B = set(map(tuple, ent_cells[1:-1]))
    if not A: return 0.0
    return len(A & B) / len(A)

def overlap_ok(candidate, existing_entries, min_frac, max_frac):
    if not existing_entries:
        return True
    # Compare to most-overlapping path
    best = 0.0
    for ent in existing_entries:
        f = _shared_fraction(candidate, ent["cells"])
        if f > best: best = f
    return (best >= min_frac) and (best <= max_frac)

# ===================== Route wrappers with uniqueness =====================
def ensure_unique_route(g, start, end, params, existing_entries, rng, max_tries, thresh, clr=None):
    cand = dijkstra_cost(g, start, end, params, forbidden=None, clr=clr)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, start, end, thresh):
        return cand
    for _ in range(max_tries):
        core = [tuple(rc) for rc in cand[1:-1]]
        if not core: break
        forbid_k = max(1, int(len(core)*0.15))
        forbid = set(random.sample(core, min(forbid_k, len(core))))
        alt = dijkstra_cost(g, start, end, params, forbidden=forbid, clr=clr)
        if alt and not is_too_similar(alt, existing_entries, start, end, thresh):
            return alt
        if alt: cand = alt
    return []  # still too similar

def ensure_unique_route_meander(g, start, end, rng, trials, existing_entries, start_bias, thresh, max_tries, clr=None):
    cand = greedy_meander(g, start, end, rng, trials, **start_bias, forbidden=None, clr=clr)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, start, end, thresh):
        return cand
    for _ in range(max_tries):
        core = [tuple(rc) for rc in cand[1:-1]]
        if not core: break
        forbid_k = max(1, int(len(core)*0.15))
        forbid = set(random.sample(core, min(forbid_k, len(core))))
        alt = greedy_meander(g, start, end, rng, max(50, trials//2), **start_bias, forbidden=forbid, clr=clr)
        if alt and not is_too_similar(alt, existing_entries, start, end, thresh):
            return alt
        if alt: cand = alt
    return []  # still too similar

# ---- Graph uniqueness wrappers ----
def ensure_unique_route_graph_shortest(graph, start_idx, end_idx, existing_entries, start, end, rng, max_tries, thresh):
    cand = graph_shortest(graph, start_idx, end_idx)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, start, end, thresh): return cand
    for _ in range(max_tries):
        alt = graph_shortest_with_penalty(graph, start_idx, end_idx, penalize_count=3)
        if alt and not is_too_similar(alt, existing_entries, start, end, thresh): return alt
    return []

def graph_shortest_with_penalty(graph, start_idx, end_idx, penalize_count=3):
    nodes, adj = graph["nodes"], graph["adj"]
    edges=[]
    for i in adj:
        for (j,L,dir_,cells) in adj[i]:
            if i<j:
                edges.append((i,j))
    rng = random.Random()
    penal_set=set(rng.sample(edges, min(penalize_count, len(edges))))
    INF=10**9
    dist=[INF]*len(nodes); prev=[None]*len(nodes); prev_edge=[None]*len(nodes)
    dist[start_idx]=0
    pq=[(0,start_idx)]
    while pq:
        d,i = heappop(pq)
        if d!=dist[i]: continue
        if i==end_idx: break
        for (j, L, dir_, cells) in adj[i]:
            pen = (L*0.8) if ((min(i,j),max(i,j)) in penal_set) else 0.0
            nd = d + L + pen
            if nd < dist[j]:
                dist[j]=nd; prev[j]=i; prev_edge[j]=(i,j,dir_,cells)
                heappush(pq,(nd,j))
    if dist[end_idx]>=INF: return []
    chain=[]; cur=end_idx
    while cur!=start_idx:
        e=prev_edge[cur]
        if e is None: break
        chain.append(e); cur=prev[cur]
    chain.reverse()
    if not chain: return []
    cells=[nodes[start_idx]]
    for (i,j,dir_,ecs) in chain: cells.extend(ecs)
    return cells

def ensure_unique_route_graph_smooth(graph, start_idx, end_idx, tau, existing_entries, start, end, rng, max_tries, thresh):
    cand = graph_smooth_turnaware(graph, start_idx, end_idx, tau=tau)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, start, end, thresh): return cand
    for _ in range(max_tries):
        alt = graph_smooth_turnaware(graph, start_idx, end_idx, tau=tau*1.15)
        if alt and not is_too_similar(alt, existing_entries, start, end, thresh): return alt
    return []

def ensure_unique_route_graph_meander(graph, start_idx, end_idx, rng, trials, existing_entries, thresh, max_tries):
    cand = graph_meander_long(graph, start_idx, end_idx, rng, trials=trials)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, graph["nodes"][start_idx], graph["nodes"][end_idx], thresh): return cand
    for _ in range(max_tries):
        alt = graph_meander_long(graph, start_idx, end_idx, rng, trials=max(50, trials//2))
        if alt and not is_too_similar(alt, existing_entries, graph["nodes"][start_idx], graph["nodes"][end_idx], thresh): return alt
    return []

def ensure_unique_route_graph_zigzag(graph, start_idx, end_idx, rng, trials, existing_entries, thresh, max_tries):
    cand = graph_zigzaggy(graph, start_idx, end_idx, rng, trials=trials)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, graph["nodes"][start_idx], graph["nodes"][end_idx], thresh): return cand
    for _ in range(max_tries):
        alt = graph_zigzaggy(graph, start_idx, end_idx, rng, trials=max(50, trials//2))
        if alt and not is_too_similar(alt, existing_entries, graph["nodes"][start_idx], graph["nodes"][end_idx], thresh): return alt
    return []

# ===================== Drawing (batched meshes) =====================
def _build_batched_tile_mesh(name_prefix, positions, color, geom, base_z):
    cell_w,cell_h,off_x,off_y,tile_xy,tile_h,_tile_z = geom
    hw = tile_xy * 0.5

    verts = []
    faces = []
    for rc in positions:
        x,y = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
        v0 = Vector((x - hw, y - hw, base_z))
        v1 = Vector((x + hw, y - hw, base_z))
        v2 = Vector((x + hw, y + hw, base_z))
        v3 = Vector((x - hw, y + hw, base_z))
        idx = len(verts)
        verts.extend([v0, v1, v2, v3])
        faces.append([idx, idx+1, idx+2, idx+3])

    if not faces:
        return None

    top_offset = Vector((0,0,geom[5]))  # tile_h
    n = len(verts)
    verts.extend([v + top_offset for v in verts])

    faces_top = [[i+n for i in f] for f in faces]
    sides = []
    for f in faces:
        v0,v1,v2,v3 = f
        v0t,v1t,v2t,v3t = v0+n, v1+n, v2+n, v3+n
        sides.extend([
            [v0, v1, v1t, v0t],
            [v1, v2, v2t, v1t],
            [v2, v3, v3t, v2t],
            [v3, v0, v0t, v3t],
        ])

    mesh = bpy.data.meshes.new(name_prefix+"_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces + faces_top + sides)
    mesh.update()

    ob = bpy.data.objects.new(name_prefix, mesh)
    col = get_collection("maze_paths"); col.objects.link(ob)

    mat = ensure_mat(f"{name_prefix}_Mat", color)
    if ob.data.materials: ob.data.materials[0]=mat
    else: ob.data.materials.append(mat)
    return ob

def draw_tiles_for_path(name_prefix, path, color, geom, skip_cells):
    base_z = geom[6]  # tile_z_offset
    positions = [tuple(rc) for rc in path if tuple(rc) not in skip_cells]
    _build_batched_tile_mesh(name_prefix, positions, color, geom, base_z)

def draw_tiles_for_cells(name_prefix, cells, color, geom):
    base_z = geom[6] + 0.002
    positions = [tuple(rc) for rc in sorted(cells)]
    _build_batched_tile_mesh(name_prefix, positions, color, geom, base_z)

# -------- Batched walls (single mesh object "MazeWalls") --------
def build_batched_walls_object(name, blocks, cell_w, cell_h, off_x, off_y, height_min, height_max, uniform_height, wall_color, target_col):
    verts = []
    faces = []
    for (r,c,h,w) in blocks:
        sx = w * cell_w
        sy = h * cell_h
        sz = height_max if uniform_height else random.uniform(height_min, height_max)

        cx = off_x + c * cell_w + (w - 1) * cell_w / 2
        cy = -(off_y + r * cell_h + (h - 1) * cell_h / 2)

        x0, x1 = cx - sx/2, cx + sx/2
        y0, y1 = cy - sy/2, cy + sy/2
        z0, z1 = 0.0, sz

        idx = len(verts)
        b0 = Vector((x0, y0, z0)); b1 = Vector((x1, y0, z0))
        b2 = Vector((x1, y1, z0)); b3 = Vector((x0, y1, z0))
        t0 = Vector((x0, y0, z1)); t1 = Vector((x1, y0, z1))
        t2 = Vector((x1, y1, z1)); t3 = Vector((x0, y1, z1))
        verts.extend([b0,b1,b2,b3,t0,t1,t2,t3])

        faces.extend([
            [idx+0, idx+1, idx+5, idx+4],
            [idx+1, idx+2, idx+6, idx+5],
            [idx+2, idx+3, idx+7, idx+6],
            [idx+3, idx+0, idx+4, idx+7],
            [idx+4, idx+5, idx+6, idx+7],
        ])

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()

    ob = bpy.data.objects.new(name, mesh)
    target_col.objects.link(ob)

    mat = ensure_mat("MazeWall", wall_color)
    if ob.data.materials: ob.data.materials[0]=mat
    else: ob.data.materials.append(mat)
    return ob

# ===================== Properties =====================
class MMM_Props(PropertyGroup):
    # ---- Maze & Randomness
    rows: IntProperty(name="Rows", default=22, min=5, soft_max=300, description="Number of passage rows (not counting walls). Larger = bigger maze.")
    cols: IntProperty(name="Cols", default=34, min=5, soft_max=300, description="Number of passage columns. Larger = bigger maze.")
    randomize: BoolProperty(name="Random Seed", default=True, description="ON: new random seed on each Generate. OFF: use Seed for reproducible mazes.")
    seed: IntProperty(name="Seed", default=12345, min=0, description="Used when Random Seed is OFF; same seed = same maze.")

    # ---- Geometry & Floor
    cell_w: FloatProperty(name="Cell W", default=2.5, min=0.05, description="World X size of one grid cell (affects wall spacing and tile spacing).")
    cell_h: FloatProperty(name="Cell H", default=2.5, min=0.05, description="World Y size of one grid cell.")
    height_min: FloatProperty(name="Wall H min", default=7.0, min=0.05, description="Minimum wall height (used if Uniform Height is OFF).")
    height_max: FloatProperty(name="Wall H max", default=20.0, min=0.05, description="Maximum wall height (used if Uniform Height is OFF).")
    uniform_height: BoolProperty(name="Uniform Height", default=False, description="ON: All walls use max height; OFF: Random height between min/max.")
    make_floor: BoolProperty(name="Make Floor", default=True, description="Creates a single floor slab under the maze.")
    floor_thickness: FloatProperty(name="Floor Thickness", default=0.2, min=0.0, description="Thickness of the generated floor slab.")

    # ---- Materials
    wall_color: FloatVectorProperty(name="Wall Color", subtype='COLOR', size=4, default=(1,1,1,1), description="Base color for maze walls.")
    wall_mat_name: StringProperty(name="Wall Material", default="MazeWall", description="Material name to assign to all maze walls.")
    floor_mat_name: StringProperty(name="Floor Material", default="MazeFloor", description="Material name for the floor slab.")

    # ---- Path Tiles & Colors
    tile_size: FloatProperty(name="Tile Size", default=0.90, min=0.1, max=1.5, description="Square tile width/height. 1.0 ~ cell size; <1 leaves a gap around tiles.")
    tile_height: FloatProperty(name="Tile Height", default=0.05, min=0.005, description="Extruded thickness of each path tile.")
    tile_z_offset: FloatProperty(name="Tile Z Offset", default=0.03, min=0.0, description="Raises path tiles slightly above floor to avoid z-fighting.")
    start_color: FloatVectorProperty(name="Start Color", subtype='COLOR', size=4, default=(1.0,0.25,0.25,1.0), description="Tile color for the start cell.")
    col_intersection: FloatVectorProperty(name="Intersection Color", subtype='COLOR', size=4, default=(0.7,0.2,0.2,1), description="Color used where two or more paths overlap.")

    # ---- Styles (4)
    use_purist: BoolProperty(name="Purist", default=True, description="Shortest path by steps (minimal turns).")
    col_purist: FloatVectorProperty(name="Purist Color", subtype='COLOR', size=4, default=(0.2,0.7,1.0,1), description="Tile color for the Purist path.")

    use_smooth: BoolProperty(name="Smooth", default=True, description="Minimize turns (fewest corners).")
    col_smooth: FloatVectorProperty(name="Smooth Color", subtype='COLOR', size=4, default=(0.4,1.0,0.8,1), description="Tile color for the Smooth path.")

    use_explorative: BoolProperty(name="Explorative", default=True, description="Long, scenic, self-avoiding route (greedy meander).")
    col_explorative: FloatVectorProperty(name="Explorative Color", subtype='COLOR', size=4, default=(1.0,0.85,0.2,1), description="Tile color for the Explorative path.")

    use_zigzag: BoolProperty(name="Zigzag", default=False, description="Maximize turns without repeats (expressive).")
    col_zigzag: FloatVectorProperty(name="Zigzag Color", subtype='COLOR', size=4, default=(1.0,0.5,0.9,1), description="Tile color for the Zigzag path.")

    explorative_trials: IntProperty(name="Greedy Trials", default=800, min=100, soft_max=6000, description="How hard the Explorative solver tries to find a long simple path (higher = longer runtime, potentially longer route).")

    # ---- Uniqueness guard
    enforce_unique: BoolProperty(name="Enforce Uniqueness", default=True, description="Avoid near-duplicate routes across styles.")
    unique_jaccard_max: FloatProperty(name="Max Similarity", default=0.85, min=0.5, max=0.99, description="If Jaccard similarity ≥ this threshold (ignoring endpoints), a path is considered too similar and will be rerouted or skipped.")
    unique_reroute_tries: IntProperty(name="Reroute Tries", default=8, min=0, max=50, description="How many alternate reroute attempts to try when a path is too similar.")

    # ---- Intersection control
    enforce_overlap: BoolProperty(
        name="Control Intersections",
        default=True,
        description="Keep paths logically related but distinct. Each new path must share between Min and Max fraction of its cells with the most-overlapping existing path."
    )
    min_shared_frac: FloatProperty(
        name="Min Shared Fraction",
        default=0.05, min=0.0, max=0.5,
        description="Lower bound on overlap with the most-overlapping existing path (ignoring endpoints). 0.05 ≈ 5%."
    )
    max_shared_frac: FloatProperty(
        name="Max Shared Fraction",
        default=0.35, min=0.05, max=0.6,
        description="Upper bound on overlap with the most-overlapping existing path (ignoring endpoints). 0.35 ≈ 35%."
    )

    # ---- Append behavior (visible after first build)
    append_paths: BoolProperty(name="Append New Paths", default=False, description="ON: add new styles on top of existing paths; OFF: replace overlays.")

    # ---- Performance
    use_graph_accel: BoolProperty(
        name="Fast Graph Acceleration",
        description="Solve on a compressed corridor graph (junctions + straight runs). Huge speedup on large mazes.",
        default=True
    )
    fast_mode: BoolProperty(
        name="Extra Fast Mode",
        description="Reduce meander trials and uniqueness reroutes for speed. Best for previews.",
        default=False
    )

# ===================== Simple route helpers (for fallback/raw) =====================
def simple_route_grid(bitmap, start, end, solver, params, rng, trials, clr):
    if solver == "DIJK":
        return dijkstra_cost(bitmap, start, end, params, forbidden=None, clr=clr)
    else:
        return greedy_meander(bitmap, start, end, rng, trials,
                              bias_turn=params.get("bias_turn", 0.0),
                              bias_open=params.get("bias_open", 0.0),
                              bias_goal=params.get("bias_goal", -0.7),
                              forbidden=None, clr=clr)

def simple_route_graph(graph, si, ei, name, rng, trials):
    if name == "PURIST":
        return graph_shortest(graph, si, ei)
    if name == "SMOOTH":
        return graph_smooth_turnaware(graph, si, ei, tau=0.9)
    if name == "EXPERIENTIAL":
        return graph_meander_long(graph, si, ei, rng, trials=trials)
    if name == "ZIGZAG":
        return graph_zigzaggy(graph, si, ei, rng, trials=max(150, trials//2))
    return []

# ===================== Operators =====================
class MMM_OT_Generate(Operator):
    bl_idname = "mmm.generate"
    bl_label = "Generate Maze (Walls + Floor)"
    bl_description = "Creates a fresh Prim's maze, walls, and optional floor. Caches the grid for pathfinding."

    def execute(self, context):
        p=context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)
        maze_col = get_collection("maze"); paths_col=get_collection("maze_paths")
        clear_collection(maze_col); clear_collection(paths_col)

        bitmap, H, W, s_open, e_open = prims_maze(p.rows, p.cols, rng)

        # Optional: carve a few loops while preserving dead-ends
        def count_passages_and_deadends(grid):
            rows, cols = len(grid), len(grid[0]); passages=0; dead=0
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

        start = inward(s_open, H, W); end = inward(e_open, H, W)

        total_w, total_h = W*p.cell_w, H*p.cell_h
        off_x, off_y = -total_w/2 + p.cell_w/2, -total_h/2 + p.cell_h/2

        # Walls (BATCHED into one object)
        wall_mat = ensure_mat(p.wall_mat_name, tuple(p.wall_color))
        blocks = merge_rectangles(bitmap, H, W)
        walls_obj = build_batched_walls_object(
            name="MazeWalls",
            blocks=blocks,
            cell_w=p.cell_w, cell_h=p.cell_h,
            off_x=off_x, off_y=off_y,
            height_min=p.height_min, height_max=p.height_max,
            uniform_height=p.uniform_height,
            wall_color=tuple(p.wall_color),
            target_col=get_collection("maze"),
        )
        if walls_obj and walls_obj.data.materials:
            walls_obj.data.materials[0] = wall_mat

        # Floor
        if p.make_floor:
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
            floor=bpy.context.active_object; floor.name="MazeFloor"
            floor.dimensions=(total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
            sit_on_ground(floor)
            floor_mat = ensure_mat(p.floor_mat_name, (0.14,0.14,0.16,1))
            if floor.data.materials: floor.data.materials[0]=floor_mat
            else: floor.data.materials.append(floor_mat)
            link_exclusive(floor, get_collection("maze"))

        # Cache (+ precomputed clearance + graph)
        clr = clearance_score(bitmap)
        graph = build_corridor_graph(bitmap, start, end)
        cache = _default_cache()
        cache.update({
            "bitmap": copy.deepcopy(bitmap),
            "rows": H, "cols": W,
            "start": start, "end": end,
            "off_x": off_x, "off_y": off_y,
            "cell_w": p.cell_w, "cell_h": p.cell_h,
            "paths": [],
            "clearance": clr,
            "graph": graph,
            "metrics": [],
            "metrics_summary": {}
        })
        set_cache(context.scene, cache)

        self.report({'INFO'}, f"Maze {H}x{W} generated (batched walls). Use 'Build Path Tiles (All Enabled)'.")
        return {'FINISHED'}

class MMM_OT_BuildPaths(Operator):
    bl_idname = "mmm.build_paths"
    bl_label = "Build Path Tiles (All Enabled)"
    bl_description = "Generate colored floor tiles for all enabled styles at once. Auto-computes intersections, uniqueness, and intersection bounds."

    def execute(self, context):
        p=context.scene.mmm_props
        cache = get_cache(context.scene)
        if not cache or not cache.get("bitmap"):
            self.report({'WARNING'}, "Generate the maze first."); return {'CANCELLED'}

        prefs = bpy.context.preferences
        prev_undo = prefs.edit.use_global_undo
        prefs.edit.use_global_undo = False
        prev_lock = bpy.context.scene.render.use_lock_interface
        bpy.context.scene.render.use_lock_interface = True
        try:
            bitmap = cache["bitmap"]
            start, end = tuple(cache["start"]), tuple(cache["end"])
            off_x, off_y = cache["off_x"], cache["off_y"]
            cell_w, cell_h = cache["cell_w"], cache["cell_h"]
            clr = cache.get("clearance")
            graph = cache.get("graph")
            use_graph = bool(p.use_graph_accel and graph)

            T0 = time.perf_counter()

            styles=[]
            if p.use_purist:       styles.append(("PURIST","DIJK", dict(step=1.0, turn=0.0, alley=0.0), tuple(p.col_purist)))
            if p.use_smooth:       styles.append(("SMOOTH","DIJK", dict(step=1.0, turn=0.9, alley=0.0), tuple(p.col_smooth)))
            if p.use_explorative: styles.append(("EXPERIENTIAL","MEAN", dict(bias_turn=0.6, bias_open=0.6, bias_goal=-0.6), tuple(p.col_explorative)))
            if p.use_zigzag:       styles.append(("ZIGZAG","MEAN", dict(bias_turn=1.2, bias_open=0.0, bias_goal=-0.4), tuple(p.col_zigzag)))
            if not styles:
                self.report({'WARNING'}, "No styles enabled."); return {'CANCELLED'}

            rng = random.Random(None if p.randomize else p.seed)
            paths_col = get_collection("maze_paths")

            has_existing = isinstance(cache.get("paths"), list) and bool(cache["paths"])
            append = bool(p.append_paths and has_existing)

            existing = list(cache.get("paths", []))
            if not append:
                clear_collection(paths_col)
                existing = []
                cache["paths"] = []

            if (not append) or (not any(o.name=="StartTile" for o in paths_col.objects)):
                sx,sy = rc_to_world(off_x, off_y, cell_w, cell_h, start)
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sx,sy,0.0))
                st=bpy.context.active_object; st.name="StartTile"
                st.dimensions=(p.tile_size, p.tile_size, p.tile_height)
                sit_on_ground(st); st.location.z += p.tile_z_offset
                sm=ensure_mat("StartColor", tuple(p.start_color))
                if st.data.materials: st.data.materials[0]=sm
                else: st.data.materials.append(sm)
                link_exclusive(st, paths_col)

            trials = p.explorative_trials if not p.fast_mode else max(100, p.explorative_trials//4)
            reroutes = p.unique_reroute_tries if not p.fast_mode else max(2, p.unique_reroute_tries//2)

            if use_graph:
                nodes = graph["nodes"]; idx_of = {rc:i for i,rc in enumerate(nodes)}
                si = idx_of.get(start); ei = idx_of.get(end)
                if si is None or ei is None:
                    use_graph = False

            per_metrics_now = []
            built=0; new_entries=[]

            # ---- helper: try build one route with uniqueness + overlap bounds, with fallback
            def try_build_named(name, solver, params, color):
                nonlocal built, existing, new_entries
                # route attempt with selected solver stack
                def attempt_one():
                    if use_graph:
                        if p.enforce_unique:
                            if name=="PURIST":
                                return ensure_unique_route_graph_shortest(graph, si, ei, existing, start, end, rng, max_tries=reroutes, thresh=p.unique_jaccard_max)
                            elif name=="SMOOTH":
                                return ensure_unique_route_graph_smooth(graph, si, ei, tau=0.9, existing_entries=existing, start=start, end=end, rng=rng, max_tries=reroutes, thresh=p.unique_jaccard_max)
                            elif name=="EXPERIENTIAL":
                                return ensure_unique_route_graph_meander(graph, si, ei, rng, trials=trials, existing_entries=existing, thresh=p.unique_jaccard_max, max_tries=reroutes)
                            else:
                                return ensure_unique_route_graph_zigzag(graph, si, ei, rng, trials=max(150, trials//2), existing_entries=existing, thresh=p.unique_jaccard_max, max_tries=reroutes)
                        else:
                            return simple_route_graph(graph, si, ei, name, rng, trials)
                    # grid fallback
                    if p.enforce_unique:
                        if solver=="DIJK":
                            return ensure_unique_route(bitmap, start, end, params, existing, rng,
                                                       max_tries=reroutes, thresh=p.unique_jaccard_max, clr=clr)
                        else:
                            return ensure_unique_route_meander(bitmap, start, end, rng, trials,
                                                               existing, start_bias=params, thresh=p.unique_jaccard_max,
                                                               max_tries=reroutes, clr=clr)
                    else:
                        return simple_route_grid(bitmap, start, end, solver, params, rng, trials, clr)

                t_s = time.perf_counter()
                route = attempt_one()
                # if graph returned nothing: fallback to grid raw
                if not route and use_graph:
                    route = simple_route_grid(bitmap, start, end, solver, params, rng, trials, clr)
                t_e = time.perf_counter()

                if not route:
                    print(f"[{name}] no route found with current settings.")
                    return

                # --- overlap control (bounds) ---
                if p.enforce_overlap and existing:
                    ok = overlap_ok(route, existing, p.min_shared_frac, p.max_shared_frac)
                    tries = reroutes
                    while (not ok) and tries>0:
                        tries -= 1
                        # cheap steer: forbid top 20% overlapped cells against the most-overlapping path
                        worst_ent=None; best=0.0
                        for ent in existing:
                            f=_shared_fraction(route, ent["cells"])
                            if f>best: best=f; worst_ent=ent
                        forbid_pool = list(set(map(tuple, route[1:-1])) & set(map(tuple, worst_ent["cells"][1:-1]))) if worst_ent else []
                        forbid = set(random.sample(forbid_pool, max(1, int(0.2*len(forbid_pool))))) if forbid_pool else set()
                        # reroute on grid (guaranteed), using DIJK/meander with forbid
                        if solver=="DIJK":
                            route = dijkstra_cost(bitmap, start, end, params, forbidden=forbid, clr=clr)
                        else:
                            route = greedy_meander(bitmap, start, end, rng, max(50,trials//2),
                                                   bias_turn=params.get("bias_turn",0.0),
                                                   bias_open=params.get("bias_open",0.0),
                                                   bias_goal=params.get("bias_goal",-0.7),
                                                   forbidden=forbid, clr=clr)
                        if not route:
                            route = attempt_one()  # try original again if forbid collapses
                        ok = bool(route) and overlap_ok(route, existing, p.min_shared_frac, p.max_shared_frac)

                    if not route or not ok:
                        print(f"[{name}] route violated intersection bounds; skipped.")
                        return

                tag = f"{name}#{sum(1 for e in (existing+new_entries) if e['key'].startswith(name))+1}" if append else name
                entry={"key": tag, "cells": [tuple(rc) for rc in route], "color": color}
                new_entries.append(entry); existing.append(entry); built += 1

                turns = _count_turns_on_cells(route) if route else 0
                per_metrics_now.append({
                    "key": tag,
                    "len": len(route),
                    "turns": turns,
                    "ms": round((t_e - t_s)*1000.0, 2),
                    "graph": bool(use_graph),
                })

            # ---- build all styles
            for (name, solver, params, color) in styles:
                try_build_named(name, solver, params, color)

            cache["paths"] = list(existing)
            set_cache(context.scene, cache)

            # Redraw overlays (batched)
            clear_collection(paths_col, name_prefixes=("Path_", "Path_Intersections_"))

            # Intersections (cells used by ≥2 paths)
            counts=Counter()
            for ent in cache["paths"]:
                for rc in ent["cells"]:
                    counts[tuple(rc)] += 1
            overlap_cells = {rc for rc,n in counts.items() if n>=2}

            geom=(cell_w,cell_h,off_x,off_y,p.tile_size,p.tile_height,p.tile_z_offset)

            for ent in cache["paths"]:
                draw_tiles_for_path(f"Path_{ent['key']}", ent["cells"], ent["color"], geom, skip_cells=overlap_cells)

            if overlap_cells:
                draw_tiles_for_cells("Path_Intersections", overlap_cells, tuple(p.col_intersection), geom)

            # ----- Metrics summary & cache -----
            metrics_map = {m["key"]: m for m in per_metrics_now}
            all_metrics = []
            for ent in cache["paths"]:
                k = ent["key"]
                if k in metrics_map:
                    all_metrics.append(metrics_map[k])
                else:
                    all_metrics.append({
                        "key": k,
                        "len": len(ent["cells"]),
                        "turns": _count_turns_on_cells(ent["cells"]),
                        "ms": None,
                        "graph": bool(use_graph),
                    })

            ms_total = round((time.perf_counter() - T0)*1000.0, 2)
            cache["metrics"] = all_metrics
            cache["metrics_summary"] = {
                "total_paths": len(cache["paths"]),
                "intersections": len(overlap_cells),
                "ms_total": ms_total,
                "graph_used": bool(use_graph),
            }
            set_cache(context.scene, cache)

            self.report({'INFO'}, f"Built {built} new path(s). Total: {len(cache['paths'])}. Intersections: {len(overlap_cells)}")
            return {'FINISHED'}
        finally:
            prefs.edit.use_global_undo = prev_undo
            bpy.context.scene.render.use_lock_interface = prev_lock

class MMM_OT_ClearPaths(Operator):
    bl_idname = "mmm.clear_paths"
    bl_label = "Clear Paths Only"
    bl_description = "Removes all path tiles and resets the path cache. Keeps walls/floor intact."
    def execute(self, context):
        paths_col = get_collection("maze_paths")
        clear_collection(paths_col)
        cache = get_cache(context.scene) or _default_cache()
        cache["paths"] = []
        cache["metrics"] = []
        cache["metrics_summary"] = {}
        set_cache(context.scene, cache)
        self.report({'INFO'}, "Cleared path overlays & cache.")
        return {'FINISHED'}

class MMM_OT_Export(Operator):
    bl_idname = "mmm.export"
    bl_label = "Export (OBJ/FBX/GLB)"
    export_format: EnumProperty(
        name="Format",
        items=[('OBJ',"OBJ","Wavefront OBJ"),('FBX',"FBX","Autodesk FBX"),('GLB',"GLB","glTF Binary")],
        default='GLB',
        description="Export your maze and (optionally) path tiles."
    )
    include_paths: BoolProperty(name="Include Paths", default=True, description="Include floor tiles for paths and intersections.")
    join_mode: EnumProperty(
        name="Mode",
        items=[('SEPARATE',"Separate Objects","Export each mesh separately"),
               ('MERGED',"Single Mesh","Export a temporary joined mesh")],
        default='SEPARATE',
        description="SEPARATE: retain objects. MERGED: one combined mesh."
    )
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')

    def invoke(self, context, event):
        ext={ 'OBJ':".obj",'FBX':".fbx",'GLB':".glb"}[self.export_format]
        if not self.filepath: self.filepath=bpy.path.abspath(f"//maze{ext}")
        context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}

    def execute(self, context):
        def select_only(objs):
            bpy.ops.object.select_all(action='DESELECT')
            for o in objs:
                try: o.select_set(True)
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
            if temp: select_only([temp]); bpy.ops.object.delete()
            return {'CANCELLED'}
        if temp: select_only([temp]); bpy.ops.object.delete()
        self.report({'INFO'}, f"Exported to {fp}")
        return {'FINISHED'}

# ===================== UI =====================
class MMM_PT_Main(Panel):
    bl_label = "Mo's Maze Maker"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mo's Maze Maker"

    def draw(self, context):
        p=context.scene.mmm_props; L=self.layout

        # ---- Maze Size & Randomness
        box=L.box(); box.label(text="Maze Size & Randomness — Prim's", icon='MESH_GRID')
        box.label(text="Controls the logical maze grid. Rows/Cols affect difficulty & shape.")
        row=box.row(align=True); row.prop(p,"rows"); row.prop(p,"cols")
        row=box.row(align=True); row.prop(p,"randomize")
        if not p.randomize: row.prop(p,"seed")

        # ---- Geometry & Floor
        box=L.box(); box.label(text="Geometry & Floor", icon='MOD_SOLIDIFY')
        box.label(text="Scales the world mesh and floor. Uniform Height forces consistent wall height.")
        row=box.row(align=True); row.prop(p,"cell_w"); row.prop(p,"cell_h")
        row=box.row(align=True); row.prop(p,"height_min"); row.prop(p,"height_max")
        box.prop(p,"uniform_height")
        row=box.row(align=True); row.prop(p,"make_floor"); row.prop(p,"floor_thickness")

        # ---- Materials
        box=L.box(); box.label(text="Materials", icon='MATERIAL')
        box.label(text="Choose material names & base wall color. Floor gets a neutral material.")
        row=box.row(align=True); row.prop(p,"wall_color"); box.prop(p,"wall_mat_name")
        box.prop(p,"floor_mat_name")

        L.operator("mmm.generate", icon='MESH_CUBE', text="Generate Maze (Walls + Floor)")

        L.separator()

        # ---- Path Tiles & Colors
        box=L.box(); box.label(text="Path Tiles & Colors", icon='EVENT_T')
        box.label(text="Tile geometry sits on the floor for readability. Intersection tiles use a special color.")
        row=box.row(align=True); row.prop(p,"tile_size"); row.prop(p,"tile_height"); row.prop(p,"tile_z_offset")
        row=box.row(align=True); row.prop(p,"start_color"); row.prop(p,"col_intersection")

        # ---- Styles
        box=L.box(); box.label(text="Path Styles (4)", icon='IPO_BEZIER')
        box.label(text="Enable styles, assign colors. Each style finds a distinct route if possible.")
        row=box.row(align=True); row.prop(p,"use_purist");      row.prop(p,"col_purist")
        row=box.row(align=True); row.prop(p,"use_smooth");      row.prop(p,"col_smooth")
        row=box.row(align=True); row.prop(p,"use_explorative");row.prop(p,"col_explorative")
        row=box.row(align=True); row.prop(p,"use_zigzag");      row.prop(p,"col_zigzag")
        box.prop(p,"explorative_trials")
        help_box = box.box()
        help_box.label(text="Style Guide:", icon='INFO')
        help_box.label(text="• Purist: shortest path by steps.")
        help_box.label(text="• Smooth: minimizes turns (flow).")
        help_box.label(text="• Explorative: long scenic route (self-avoiding).")
        help_box.label(text="• Zigzag: many turns, expressive pattern.")

        # ---- Uniqueness
        box=L.box(); box.label(text="Uniqueness Guard", icon='MOD_PHYSICS')
        box.label(text="Prevents near-duplicate routes. Higher Max Similarity allows more overlap; Reroute Tries tries to diversify.")
        row=box.row(align=True); row.prop(p,"enforce_unique"); row.prop(p,"unique_jaccard_max")
        row=box.row(align=True); row.prop(p,"unique_reroute_tries")

        # ---- Intersection Control
        box=L.box(); box.label(text="Intersection Control", icon='OVERLAY')
        box.label(text="Keep paths distinct but related. Each new path shares between Min and Max with the most-overlapping existing path.")
        row=box.row(align=True); row.prop(p,"enforce_overlap")
        row=box.row(align=True); row.prop(p,"min_shared_frac"); row.prop(p,"max_shared_frac")

        # ---- Performance
        box=L.box(); box.label(text="Performance", icon='SORTTIME')
        box.prop(p, "use_graph_accel")
        box.prop(p, "fast_mode")
        help_perf = box.box()
        help_perf.label(text="Graph Acceleration solves on a tiny network of corridors and junctions, then expands to tiles.")
        help_perf.label(text="Extra Fast Mode lowers meander trials & reroute attempts for preview-speed builds.")

        # ---- Build behavior (Append)
        cache = get_cache(context.scene, read_only=True)
        has_paths = bool(cache.get("paths"))
        if has_paths:
            box=L.box(); box.label(text="Build Behavior", icon='PLUS')
            box.label(text="Append keeps existing tiles and adds more on top. Off = replace overlays.")
            box.prop(p,"append_paths")

        # ---- Actions
        L.operator("mmm.build_paths", icon='MOD_BUILD', text="Build Path Tiles (All Enabled)")
        L.operator("mmm.clear_paths", icon='TRASH', text="Clear Paths Only")

        L.separator()
        # ---- Export
        box=L.box(); box.label(text="Export", icon='EXPORT')
        box.label(text="Export maze (and optionally tiles) as OBJ/FBX/GLB. MERGED joins into one mesh for compact output.")
        box.operator("mmm.export", icon='EXPORT', text="Export (OBJ/FBX/GLB)")

class MMM_PT_Metrics(Panel):
    bl_label = "Mo's Maze Maker — Metrics"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mo's Maze Maker"

    def draw(self, context):
        L = self.layout
        cache = get_cache(context.scene, read_only=True)
        paths = cache.get("paths") or []
        metrics = cache.get("metrics") or []
        summary = cache.get("metrics_summary") or {}

        if not paths:
            L.label(text="No path data yet. Build Path Tiles first.", icon='INFO')
            return

        # Summary
        box = L.box()
        box.label(text="Summary", icon='INFO')
        row = box.row(align=True)
        row.label(text=f"Total paths: {summary.get('total_paths','–')}")
        row.label(text=f"Intersections: {summary.get('intersections','–')}")
        row = box.row(align=True)
        row.label(text=f"Build time: {summary.get('ms_total','–')} ms")
        row.label(text=f"Graph Accel: {'ON' if summary.get('graph_used') else 'OFF'}")

        # Per-path
        box = L.box()
        box.label(text="Per-Path", icon='SEQ_LUMA_WAVEFORM')
        for m in metrics:
            row = box.row(align=True)
            key = m.get("key","?")
            ln  = m.get("len","–")
            tn  = m.get("turns","–")
            ms  = m.get("ms")
            gr  = m.get("graph", False)
            row.label(text=f"{key}")
            row.label(text=f"Len: {ln}")
            row.label(text=f"Turns: {tn}")
            row.label(text=f"Solver: {'Graph' if gr else 'Grid'}")
            row.label(text=("Time: {:.2f} ms".format(ms)) if ms is not None else "Time: —")

# ===================== Register =====================
classes=(
    MMM_Props,
    MMM_OT_Generate,
    MMM_OT_BuildPaths,
    MMM_OT_ClearPaths,
    MMM_OT_Export,
    MMM_PT_Main,
    MMM_PT_Metrics,
)
def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.mmm_props = PointerProperty(type=MMM_Props)
def unregister():
    del bpy.types.Scene.mmm_props
    for c in reversed(classes): bpy.utils.unregister_class(c)
if __name__=="__main__":
    register()

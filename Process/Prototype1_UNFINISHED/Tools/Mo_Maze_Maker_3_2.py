bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G's brains (plus ChatGPT brawn)",
    "version": (3, 2, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A maze generator exploring parsimony.",
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
    }
def get_cache(scene, read_only=False):
    k = scene.as_pointer()
    data = MODULE_CACHE.get(k)
    if data is None:
        return _default_cache() if read_only else None
    return data
def set_cache(scene, data):
    MODULE_CACHE[scene.as_pointer()] = data
    MODULE_CACHE["__last__"] = data  # fallback

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
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
    bsdf.inputs["Roughness"].default_value = 0.55
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
# Prim's maze generation (grid with walls=True, passages=False)
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

    # single start/end openings on opposite borders
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
# City Look: convert each wall block to sub-lots of buildings (unchanged maze)
# ──────────────────────────────────────────────────────────────────────────────
def _block_rect_world(off_x, off_y, cell_w, cell_h, r, c, h, w):
    sx=w*cell_w; sy=h*cell_h
    cx = off_x + c*cell_w + (w-1)*cell_w/2.0
    cy = -(off_y + r*cell_h + (h-1)*cell_h/2.0)
    return (cx - sx/2.0, cx + sx/2.0, cy - sy/2.0, cy + sy/2.0)

def _shrink_rect_by(rect, inset):
    x0,x1,y0,y1 = rect
    return (x0+inset, x1-inset, y0+inset, y1-inset)

def _split_range(total_cells, kmin, kmax, rng):
    parts=[]; remain=max(1, total_cells)
    kmin=max(1,kmin); kmax=max(kmin,kmax)
    while remain>0:
        k = min(remain, rng.randint(kmin, kmax))
        parts.append(k); remain -= k
    return parts

def build_batched_prisms(name, rects_world, heights, color, target_col, mat_name=None):
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

def cityify_wall_blocks_as_buildings(blocks, off_x, off_y, cell_w, cell_h,
                                     lot_min, lot_max, setback_m,
                                     hmin, hmax, roof_step,
                                     color_rgba, target_col, rng, add_bevel=True):
    rects_world=[]; heights=[]
    for (r,c,h,w) in blocks:
        R = _block_rect_world(off_x, off_y, cell_w, cell_h, r,c,h,w)
        if setback_m > 0.0:
            R = _shrink_rect_by(R, setback_m)
        x0,x1,y0,y1 = R
        if x1 <= x0 or y1 <= y0: continue
        xs = _split_range(w, lot_min, lot_max, rng)
        ys = _split_range(h, lot_min, lot_max, rng)

        cx0=x0
        for kx in xs:
            cx1=cx0 + kx*cell_w
            cy1=y1
            for ky in ys:
                cy0=cy1 - ky*cell_h
                lot=(cx0,cx1,cy0,cy1)
                lot=_shrink_rect_by(lot, min(cell_w,cell_h)*0.08)
                if lot[1] > lot[0] and lot[3] > lot[2]:
                    rects_world.append(lot)
                    zh = rng.uniform(hmin, hmax)
                    if roof_step > 0.0: zh += rng.choice([0.0, roof_step * rng.random()])
                    heights.append(zh)
                cy1=cy0
            cx0=cx1

    ob = build_batched_prisms(
        name="CityLook_Buildings",
        rects_world=rects_world,
        heights=heights,
        color=color_rgba,
        target_col=target_col,
        mat_name="CityLook_Building_Mat"
    )
    if ob and add_bevel:
        try:
            mod = ob.modifiers.new("AutoBevel", 'BEVEL')
            mod.width = 0.06
            mod.segments = 2
            mod.limit_method = 'ANGLE'
            mod.angle_limit = math.radians(35.0)
            mod.harden_normals = True
        except: pass
    return ob

# ──────────────────────────────────────────────────────────────────────────────
# Corridor graph (junctions as nodes, straight runs as edges) — for props
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

# ──────────────────────────────────────────────────────────────────────────────
# Pathfinding (grid), uniqueness, intersections
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

def manhattan(a,b): return abs(a[0]-b[0]) + abs(a[1]-b[1])

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
            path=[]
            cur=st
            while cur in prev:
                (rr,cc,_), p = cur, prev[cur]
                path.append((rr,cc))
                cur=p
            (rr,cc,_)=cur; path.append((rr,cc))
            return path[::-1]
        for rr,cc,dr,dc in neighbors_passages(g, r, c):
            if (rr,cc) in forbidden: continue
            wc = w_cost(pi,(dr,dc),rr,cc)
            ng = g_cost + wc
            ns = (rr,cc,(dr,dc))
            if ng < dist.get(ns, INF):
                dist[ns] = ng; prev[ns] = st
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
                    seen.add((rr,cc)); Q.append((rr,cc))
        return False

    best=None
    for _ in range(trials):
        path=[start]; visited={start}; prev_dir=None
        while path[-1] != goal:
            r, c = path[-1]; cand=[]
            for rr,cc,dr,dc in neighbors_passages(g, r, c):
                if (rr,cc) in visited or (rr,cc) in forbidden: continue
                blocked = visited.copy(); blocked.add((rr,cc))
                if not reachable((rr,cc), blocked - {(rr,cc)}): continue
                turn = 1.0 if (prev_dir is not None and prev_dir!=(dr,dc)) else 0.0
                open_bonus = 1.0 - (clr[rr][cc]/4.0)
                dgoal = manhattan((rr,cc), goal)
                score = (bias_turn*turn) + (bias_open*open_bonus) + (bias_goal*dgoal) + random.random()*0.05
                cand.append(((rr,cc,dr,dc), score))
            if not cand: break
            cand.sort(key=lambda x:x[1], reverse=True)
            rr,cc,dr,dc = random.choice(cand[:min(3,len(cand))])[0]
            prev_dir=(dr,dc); path.append((rr,cc)); visited.add((rr,cc))
        if path and path[-1]==goal and ((best is None) or (len(path)>len(best))):
            best=path
    return best or []

def _count_turns_on_cells(cells):
    if len(cells) < 3: return 0
    def dir_of(a,b): return (b[0]-a[0], b[1]-a[1])
    turns=0; prev=dir_of(cells[0], cells[1])
    for i in range(1, len(cells)-1):
        d=dir_of(cells[i], cells[i+1])
        if d != prev: turns += 1
        prev = d
    return turns

# similarity / overlap
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

# wrappers
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

# ──────────────────────────────────────────────────────────────────────────────
# Drawing helpers (tiles + layered corridors)
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

def _build_layered_corridor_mesh(name, bitmap, cell_w, cell_h, off_x, off_y,
                                 width_factor, height, color, z0, target_col, mat_name):
    wf = max(0.2, min(1.2, width_factor))
    w = cell_w * wf; h = cell_h * wf
    half_w = w*0.5; half_h = h*0.5
    verts=[]; faces=[]
    for r,row in enumerate(bitmap):
        for c,is_wall in enumerate(row):
            if is_wall: continue
            x,y = rc_to_world(off_x, off_y, cell_w, cell_h, (r,c))
            v0=Vector((x-half_w, y-half_h, z0))
            v1=Vector((x+half_w, y-half_h, z0))
            v2=Vector((x+half_w, y+half_h, z0))
            v3=Vector((x-half_w, y+half_h, z0))
            idx=len(verts); verts.extend([v0,v1,v2,v3]); faces.append([idx,idx+1,idx+2,idx+3])
    if not faces: return None
    # extrude thickness
    top_offset = Vector((0,0,height))
    n=len(verts); verts.extend([v+top_offset for v in verts])
    faces_top = [[i+n for i in f] for f in faces]
    sides=[]
    for f in faces:
        a,b,c,d=f; at,bt,ct,dt=a+n,b+n,c+n,d+n
        sides.extend([[a,b,bt,at],[b,c,ct,bt],[c,d,dt,ct],[d,a,at,dt]])
    mesh=bpy.data.meshes.new(name+"_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces+faces_top+sides); mesh.update()
    ob=bpy.data.objects.new(name, mesh); target_col.objects.link(ob)
    mat=ensure_mat(mat_name, color)
    if ob.data.materials: ob.data.materials[0]=mat
    else: ob.data.materials.append(mat)
    return ob

def _build_lane_marks(bitmap, cell_w, cell_h, off_x, off_y, width_factor, color, target_col):
    wf = max(0.2, min(1.0, width_factor))*0.1
    strip_w = cell_w*wf; strip_h = cell_h*0.08
    verts=[]; faces=[]
    for r,row in enumerate(bitmap):
        for c,is_wall in enumerate(row):
            if is_wall: continue
            x,y = rc_to_world(off_x, off_y, cell_w, cell_h, (r,c))
            v0=Vector((x-strip_w*0.5, y-strip_h*0.5, 0.002))
            v1=Vector((x+strip_w*0.5, y-strip_h*0.5, 0.002))
            v2=Vector((x+strip_w*0.5, y+strip_h*0.5, 0.002))
            v3=Vector((x-strip_w*0.5, y+strip_h*0.5, 0.002))
            idx=len(verts); verts.extend([v0,v1,v2,v3]); faces.append([idx,idx+1,idx+2,idx+3])
    if not faces: return None
    mesh=bpy.data.meshes.new("LaneMark_Mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces); mesh.update()
    ob=bpy.data.objects.new("LaneMark", mesh); target_col.objects.link(ob)
    mat=ensure_mat("LaneMark_Mat", color)
    if ob.data.materials: ob.data.materials[0]=mat
    else: ob.data.materials.append(mat)
    return ob

# ──────────────────────────────────────────────────────────────────────────────
# Props at junctions (instanced collection)
# ──────────────────────────────────────────────────────────────────────────────
def spawn_props_at_junctions(graph, off_x, off_y, cell_w, cell_h,
                             prop_collection="MMM_Props", target="maze", chance=1.0):
    src = bpy.data.collections.get(prop_collection)
    if not src or not src.objects:
        return 0
    dst = get_collection(target)
    nodes, adj = graph["nodes"], graph["adj"]
    n_spawn=0
    for i, rc in enumerate(nodes):
        if len(adj[i]) <= 2:
            continue  # not a junction
        if random.random() > max(0.0, min(1.0, chance)):
            continue
        px, py = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
        inst = bpy.data.objects.new(f"Junc_{i}_Prop", None)
        inst.instance_type='COLLECTION'
        inst.instance_collection = src
        inst.location = (px, py, 0.0)
        dst.objects.link(inst)
        n_spawn += 1
    return n_spawn

# ──────────────────────────────────────────────────────────────────────────────
# Properties
# ──────────────────────────────────────────────────────────────────────────────
class MMM_Props(PropertyGroup):
    # Size / randomness
    rows: IntProperty(name="Rows", default=22, min=5, soft_max=300)
    cols: IntProperty(name="Cols", default=34, min=5, soft_max=300)
    randomize: BoolProperty(name="Random Seed", default=True)
    seed: IntProperty(name="Seed", default=12345, min=0)

    # Geometry & floor
    cell_w: FloatProperty(name="Cell W", default=2.5, min=0.05)
    cell_h: FloatProperty(name="Cell H", default=2.5, min=0.05)
    height_min: FloatProperty(name="Wall H min", default=7.0, min=0.05)
    height_max: FloatProperty(name="Wall H max", default=20.0, min=0.05)
    uniform_height: BoolProperty(name="Uniform Height", default=False)
    make_floor: BoolProperty(name="Make Floor", default=True)
    floor_thickness: FloatProperty(name="Floor Thickness", default=0.2, min=0.0)
    wall_color: FloatVectorProperty(name="Wall Color", subtype='COLOR', size=4, default=(0.85,0.86,0.9,1))
    wall_mat_name: StringProperty(name="Wall Material", default="MazeWall")
    floor_mat_name: StringProperty(name="Floor Material", default="MazeFloor")

    # City Look (walls → clustered buildings)
    city_look: BoolProperty(
        name="City Look (Blocks as Buildings)", default=False,
        description="Render each wall block as clustered buildings; corridors remain identical"
    )
    city_setback: FloatProperty(name="Setback (m)", default=0.25, min=0.0, soft_max=1.0,
                                description="Keeps buildings away from corridor edges")
    city_lot_min_cells: IntProperty(name="Lot Min (cells)", default=1, min=1, soft_max=6)
    city_lot_max_cells: IntProperty(name="Lot Max (cells)", default=3, min=1, soft_max=12)
    city_h_min: FloatProperty(name="Building H min", default=6.0, min=0.5, soft_max=120.0)
    city_h_max: FloatProperty(name="Building H max", default=22.0, min=0.5, soft_max=200.0)
    city_roof_step: FloatProperty(name="Top Random Step", default=0.0, min=0.0, soft_max=1.0,
                                  description="Adds a small stepped top variation (0=off)")
    city_color: FloatVectorProperty(name="Building Color", subtype='COLOR', size=4, default=(0.78,0.80,0.85,1.0))

    # Street layers (asphalt + sidewalks + lane marks)
    enable_street_layers: BoolProperty(name="Street Layers (Asphalt+Sidewalks)", default=True)
    street_width_factor: FloatProperty(name="Asphalt Width (×cell)", default=0.58, min=0.2, max=1.0)
    sidewalk_width_factor: FloatProperty(name="Sidewalk Width (×cell)", default=0.86, min=0.3, max=1.2)
    sidewalk_height: FloatProperty(name="Sidewalk Height", default=0.08, min=0.0, max=0.3)
    asphalt_thickness: FloatProperty(name="Asphalt Thickness", default=0.04, min=0.0, max=0.2)
    asphalt_color: FloatVectorProperty(name="Asphalt Color", subtype='COLOR', size=4, default=(0.08,0.08,0.09,1))
    sidewalk_color: FloatVectorProperty(name="Sidewalk Color", subtype='COLOR', size=4, default=(0.62,0.62,0.65,1))
    draw_lane_mark: BoolProperty(name="Center Line", default=True)
    lane_marking_color: FloatVectorProperty(name="Lane Mark Color", subtype='COLOR', size=4, default=(1.0,0.95,0.2,1))
    
    # Junction props
    enable_props: BoolProperty(name="Spawn Junction Props", default=False,
                               description="Instance a collection at corridor junctions")
    prop_collection: StringProperty(name="Prop Collection", default="MMM_Props")
    prop_spawn_chance: FloatProperty(name="Prop Chance", default=1.0, min=0.0, max=1.0)

    # Path tiles
    tile_size: FloatProperty(name="Tile Size", default=0.90, min=0.1, max=1.5)
    tile_height: FloatProperty(name="Tile Height", default=0.05, min=0.005)
    tile_z_offset: FloatProperty(name="Tile Z Offset", default=0.03, min=0.0)
    start_color: FloatVectorProperty(name="Start Color", subtype='COLOR', size=4, default=(1.0,0.25,0.25,1.0))
    col_intersection: FloatVectorProperty(name="Intersection Color", subtype='COLOR', size=4, default=(0.7,0.2,0.2,1))

    # Styles
    use_purist: BoolProperty(name="Purist", default=True, description="Shortest path (fewest steps)")
    col_purist: FloatVectorProperty(name="Purist Color", subtype='COLOR', size=4, default=(0.2,0.7,1.0,1))
    use_smooth: BoolProperty(name="Smooth", default=True, description="Penalizes turns; straighter")
    col_smooth: FloatVectorProperty(name="Smooth Color", subtype='COLOR', size=4, default=(0.4,1.0,0.8,1))
    use_explorative: BoolProperty(name="Explorative", default=True, description="Longer, scenic, no repeats")
    col_explorative: FloatVectorProperty(name="Explorative Color", subtype='COLOR', size=4, default=(1.0,0.85,0.2,1))
    use_zigzag: BoolProperty(name="Zigzag", default=False, description="Turn-hungry, frequent direction changes")
    col_zigzag: FloatVectorProperty(name="Zigzag Color", subtype='COLOR', size=4, default=(1.0,0.5,0.9,1))
    explorative_trials: IntProperty(name="Greedy Trials", default=800, min=100, soft_max=6000)

    # Uniqueness / intersections
    enforce_unique: BoolProperty(name="Enforce Uniqueness", default=True)
    unique_jaccard_max: FloatProperty(name="Max Similarity", default=0.85, min=0.5, max=0.99)
    unique_reroute_tries: IntProperty(name="Reroute Tries", default=8, min=0, max=50)
    enforce_overlap: BoolProperty(name="Control Intersections", default=True)
    min_shared_frac: FloatProperty(name="Min Shared Fraction", default=0.05, min=0.0, max=0.5)
    max_shared_frac: FloatProperty(name="Max Shared Fraction", default=0.35, min=0.05, max=0.6)

    # Append & performance
    append_paths: BoolProperty(name="Append New Paths", default=False, description="Append instead of replacing")
    fast_mode: BoolProperty(name="Fast Mode", default=False, description="Reduce trials/reroutes for speed")

# ──────────────────────────────────────────────────────────────────────────────
# Operators
# ──────────────────────────────────────────────────────────────────────────────
class MMM_OT_Generate(Operator):
    bl_idname = "mmm.generate"
    bl_label = "Generate Maze / Level Look"
    bl_description = "Generate Prim's maze. Optional City Look for walls, layered streets, lane marks, and junction props."

    def execute(self, context):
        p = context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)

        maze_col = get_collection("maze")
        paths_col = get_collection("maze_paths")
        clear_collection(maze_col)
        clear_collection(paths_col)

        # Maze bitmap
        bitmap, H, W, s_open, e_open = prims_maze(p.rows, p.cols, rng)

        # Keep some dead-ends; allow a tiny loop ratio but preserve dead ends
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
        def carve_loops_with_deadend_guard(grid, H, W, rng, ratio=0.05, min_deadend_ratio=0.06, min_deadend_abs=6):
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

        start = inward(s_open, H, W)
        end   = inward(e_open,   H, W)

        # World transforms
        total_w, total_h = W*p.cell_w, H*p.cell_h
        off_x, off_y = -total_w/2 + p.cell_w/2, -total_h/2 + p.cell_h/2

        maze_target = get_collection("maze")

        # Build “walls”: either classic walls, or City Look (clustered buildings)
        blocks = merge_rectangles(bitmap, H, W)
        if p.city_look:
            cityify_wall_blocks_as_buildings(
                blocks=blocks,
                off_x=off_x, off_y=off_y,
                cell_w=p.cell_w, cell_h=p.cell_h,
                lot_min=p.city_lot_min_cells,
                lot_max=p.city_lot_max_cells,
                setback_m=p.city_setback,
                hmin=p.city_h_min, hmax=p.city_h_max,
                roof_step=p.city_roof_step,
                color_rgba=tuple(p.city_color),
                target_col=maze_target,
                rng=rng,
                add_bevel=True
            )
        else:
            rects=[]; heights=[]
            for (r,c,h,w) in blocks:
                sx=w*p.cell_w; sy=h*p.cell_h
                cx = off_x + c*p.cell_w + (w-1)*p.cell_w/2
                cy = -(off_y + r*p.cell_h + (h-1)*p.cell_h/2)
                x0, x1 = cx - sx/2, cx + sx/2
                y0, y1 = cy - sy/2, cy + sy/2
                rects.append((x0,x1,y0,y1))
                heights.append(p.height_max if p.uniform_height else random.uniform(p.height_min, p.height_max))
            build_batched_prisms("MazeWalls", rects, heights, tuple(p.wall_color), maze_target, p.wall_mat_name)

        # Ground plane (large slab)
        if p.make_floor:
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
            floor=bpy.context.active_object; floor.name="LevelGround"
            floor.dimensions=(total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
            sit_on_ground(floor)
            fm=ensure_mat(p.floor_mat_name, (0.14,0.14,0.16,1))
            if floor.data.materials: floor.data.materials[0]=fm
            else: floor.data.materials.append(fm)
            link_exclusive(floor, maze_target)

        # Layered corridors (sidewalks above asphalt) + lane marks
        if p.enable_street_layers:
            _build_layered_corridor_mesh(
                name="Sidewalks",
                bitmap=bitmap,
                cell_w=p.cell_w, cell_h=p.cell_h, off_x=off_x, off_y=off_y,
                width_factor=p.sidewalk_width_factor,
                height=p.sidewalk_height,
                color=tuple(p.sidewalk_color),
                z0=0.0,
                target_col=maze_target,
                mat_name="Sidewalk_Mat"
            )
            _build_layered_corridor_mesh(
                name="Asphalt",
                bitmap=bitmap,
                cell_w=p.cell_w, cell_h=p.cell_h, off_x=off_x, off_y=off_y,
                width_factor=p.street_width_factor,
                height=p.asphalt_thickness,
                color=tuple(p.asphalt_color),
                z0=0.0,
                target_col=maze_target,
                mat_name="Asphalt_Mat"
            )
            if p.draw_lane_mark:
                _build_lane_marks(bitmap, p.cell_w, p.cell_h, off_x, off_y,
                                  p.street_width_factor, tuple(p.lane_marking_color), maze_target)

        # Corridor graph (for props + maybe future accel)
        graph = build_corridor_graph(bitmap, start, end)
        if p.enable_props:
            n = spawn_props_at_junctions(graph, off_x, off_y, p.cell_w, p.cell_h,
                                         prop_collection=p.prop_collection,
                                         target="maze",
                                         chance=p.prop_spawn_chance)
            if n == 0:
                self.report({'INFO'}, "No props spawned (no junctions found, or source collection empty).")

        # Cache for path builder
        clr = clearance_score(bitmap)
        cache=_default_cache()
        cache.update({
            "bitmap": copy.deepcopy(bitmap), "rows": H, "cols": W,
            "start": start, "end": end,
            "off_x": off_x, "off_y": off_y, "cell_w": p.cell_w, "cell_h": p.cell_h,
            "paths": [], "clearance": clr, "graph": graph,
            "metrics": [], "metrics_summary": {},
        })
        set_cache(context.scene, cache)

        self.report({'INFO'}, f"Generated {H}x{W}. Build Path Tiles when ready.")
        return {'FINISHED'}

class MMM_OT_BuildPaths(Operator):
    bl_idname = "mmm.build_paths"
    bl_label = "Build Path Tiles (All Enabled)"
    bl_description = "Generate colored floor tiles for all enabled styles; avoids near-duplicates and controls intersections."

    def execute(self, context):
        p = context.scene.mmm_props
        cache = get_cache(context.scene)
        if not cache or not cache.get("bitmap"):
            cache = MODULE_CACHE.get("__last__")
        if not cache or not cache.get("bitmap"):
            self.report({'WARNING'}, "Generate a maze first.")
            return {'CANCELLED'}

        prefs=bpy.context.preferences
        prev_undo=prefs.edit.use_global_undo; prefs.edit.use_global_undo=False
        prev_lock=bpy.context.scene.render.use_lock_interface; bpy.context.scene.render.use_lock_interface=True
        try:
            bitmap=cache["bitmap"]; start,end=tuple(cache["start"]),tuple(cache["end"])
            off_x,off_y=cache["off_x"],cache["off_y"]
            cell_w,cell_h=cache["cell_w"],cache["cell_h"]
            clr=cache.get("clearance")

            styles=[]
            if p.use_purist:       styles.append(("PURIST","DIJK", dict(step=1.0, turn=0.0, alley=0.0), tuple(p.col_purist)))
            if p.use_smooth:       styles.append(("SMOOTH","DIJK", dict(step=1.0, turn=0.9, alley=0.0), tuple(p.col_smooth)))
            if p.use_explorative: styles.append(("EXPLORATIVE","MEAN", dict(bias_turn=0.6, bias_open=0.6, bias_goal=-0.6), tuple(p.col_explorative)))
            if p.use_zigzag:       styles.append(("ZIGZAG","MEAN", dict(bias_turn=1.2, bias_open=0.0, bias_goal=-0.4), tuple(p.col_zigzag)))
            if not styles:
                self.report({'WARNING'},"No styles enabled.")
                return {'CANCELLED'}

            rng=random.Random(None if p.randomize else p.seed)
            paths_col=get_collection("maze_paths")
            has_existing = isinstance(cache.get("paths"), list) and bool(cache["paths"])
            append = bool(p.append_paths and has_existing)
            existing = list(cache.get("paths", []))
            if not append:
                clear_collection(paths_col)
                existing=[]; cache["paths"]=[]

            # Start tile (unique)
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

            built=0; new_entries=[]; per_metrics_now=[]
            def try_build_named(name, solver, params, color):
                nonlocal built, existing, new_entries
                def attempt_one():
                    if p.enforce_unique:
                        if solver=="DIJK":
                            return ensure_unique_route(bitmap, start, end, params, existing, rng, max_tries=reroutes, thresh=p.unique_jaccard_max, clr=clr)
                        else:
                            return ensure_unique_route_meander(bitmap, start, end, rng, trials, existing, start_bias=params, thresh=p.unique_jaccard_max, max_tries=reroutes, clr=clr)
                    else:
                        return simple_route_grid(bitmap, start, end, solver, params, rng, trials, clr)

                t_s=time.perf_counter()
                route=attempt_one()
                t_e=time.perf_counter()
                if not route: return

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
                        ok = bool(route) and overlap_ok(route, existing, p.min_shared_frac, p.max_shared_frac)
                    if not route or not ok: return

                tag = f"{name}#{sum(1 for e in (existing+new_entries) if e['key'].startswith(name))+1}" if p.append_paths and cache["paths"] else name
                entry={"key":tag, "cells":[tuple(rc) for rc in route], "color": color}
                new_entries.append(entry); existing.append(entry); built+=1
                per_metrics_now.append({"key":tag,"len":len(route),"turns":_count_turns_on_cells(route),"ms":round((t_e-t_s)*1000.0,2)})

            for (name, solver, params, color) in styles:
                try_build_named(name, solver, params, color)

            cache["paths"]=list(existing); set_cache(context.scene, cache)

            # Draw tiles & intersections
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
                else: all_metrics.append({"key":k,"len":len(ent["cells"]), "turns":_count_turns_on_cells(ent["cells"]), "ms":None})
            ms_total=round((sum(m.get("ms",0) or 0 for m in per_metrics_now)),2)
            cache["metrics"]=all_metrics
            cache["metrics_summary"]={"total_paths":len(cache["paths"]), "intersections":len(overlap_cells), "ms_total":ms_total}
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
# UI
# ──────────────────────────────────────────────────────────────────────────────
class MMM_PT_Main(Panel):
    bl_label="Mo's Maze Maker"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category="Mo's Maze Maker"

    def draw(self, context):
        p=context.scene.mmm_props; L=self.layout

        # Maze size
        box=L.box(); box.label(text="Maze Size & Randomness — Prim's", icon='MESH_GRID')
        row=box.row(align=True); row.prop(p,"rows"); row.prop(p,"cols")
        row=box.row(align=True); row.prop(p,"randomize"); 
        if not p.randomize: row.prop(p,"seed")

        # Geometry / materials
        box=L.box(); box.label(text="Geometry & Floor", icon='MOD_SOLIDIFY')
        row=box.row(align=True); row.prop(p,"cell_w"); row.prop(p,"cell_h")
        row=box.row(align=True); row.prop(p,"height_min"); row.prop(p,"height_max")
        box.prop(p,"uniform_height")
        row=box.row(align=True); row.prop(p,"make_floor"); row.prop(p,"floor_thickness")
        row=box.row(align=True); row.prop(p,"wall_color"); row.prop(p,"wall_mat_name")
        box.prop(p,"floor_mat_name")

        # City Look
        box=L.box(); box.label(text="City Look (Walls → Buildings)", icon='HOME')
        box.prop(p, "city_look")
        row=box.row(align=True); row.prop(p, "city_setback"); row.prop(p, "city_roof_step")
        row=box.row(align=True); row.prop(p, "city_lot_min_cells"); row.prop(p, "city_lot_max_cells")
        row=box.row(align=True); row.prop(p, "city_h_min"); row.prop(p, "city_h_max")
        box.prop(p, "city_color")

        # Street Layers
        box=L.box(); box.label(text="Street Layers (Walkable Readability)", icon='OUTLINER_OB_LIGHTPROBE')
        box.prop(p,"enable_street_layers")
        col=box.column(align=True); col.enabled=p.enable_street_layers
        row=col.row(align=True); row.prop(p,"sidewalk_width_factor"); row.prop(p,"street_width_factor")
        row=col.row(align=True); row.prop(p,"sidewalk_height"); row.prop(p,"asphalt_thickness")
        row=col.row(align=True); row.prop(p,"sidewalk_color"); row.prop(p,"asphalt_color")
        row=col.row(align=True); row.prop(p,"draw_lane_mark"); row.prop(p,"lane_marking_color")

        # Junction props
        box=L.box(); box.label(text="Junction Props (Landmarks)", icon='OUTLINER_COLLECTION')
        box.prop(p,"enable_props")
        col=box.column(align=True); col.enabled=p.enable_props
        col.prop(p,"prop_collection")
        col.prop(p,"prop_spawn_chance")

        L.operator("mmm.generate", icon='MESH_CUBE', text="Generate Maze / Level Look")

        L.separator()

        # Path Tiles
        box=L.box(); box.label(text="Path Tiles & Colors", icon='EVENT_T')
        row=box.row(align=True); row.prop(p,"tile_size"); row.prop(p,"tile_height"); row.prop(p,"tile_z_offset")
        row=box.row(align=True); row.prop(p,"start_color"); row.prop(p,"col_intersection")

        # Styles
        box=L.box(); box.label(text="Path Styles", icon='IPO_BEZIER')
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

        # Build / Export
        box=L.box(); box.label(text="Build & Export", icon='SORTTIME')
        row=box.row(align=True); row.prop(p,"append_paths"); row.prop(p,"fast_mode")
        L.operator("mmm.build_paths", icon='MOD_BUILD', text="Build Path Tiles (All Enabled)")
        L.operator("mmm.clear_paths", icon='TRASH', text="Clear Paths Only")

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
        row=box.row(align=True); row.label(text=f"Build time: {summary.get('ms_total','–')} ms")
        box=L.box(); box.label(text="Per-Path", icon='SEQ_LUMA_WAVEFORM')
        for m in metrics:
            row=box.row(align=True)
            row.label(text=f"{m.get('key','?')}")
            row.label(text=f"Len: {m.get('len','–')}")
            row.label(text=f"Turns: {m.get('turns','–')}")
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

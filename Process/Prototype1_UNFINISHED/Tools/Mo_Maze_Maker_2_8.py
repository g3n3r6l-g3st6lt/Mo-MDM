bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G's brains (plus ChatGPT brawn)",
    "version": (2, 8, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A maze generator exploring parsimony.",
    "category": "Add Mesh",
}

# ──────────────────────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────────────────────
import bpy, random, math, os, copy, time, json
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
        "clearance": None,
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

def ensure_mat(name, rgba=(1,1,1,1), rough=0.55):
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
    bsdf.inputs["Roughness"].default_value = rough
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

# ──────────────────────────────────────────────────────────────────────────────
# Walls: merge and build mesh
# ──────────────────────────────────────────────────────────────────────────────
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

def build_separate_cubes(rects_world, heights, color, target_col, mat_name="MazeWall"):
    """One object per merged wall block (length/width/height)."""
    mat = ensure_mat(mat_name, color)
    created = []
    for i, ((x0,x1,y0,y1), z1) in enumerate(zip(rects_world, heights), start=1):
        sx = (x1 - x0)
        sy = (y1 - y0)
        sz = max(0.001, z1)
        cx = (x0 + x1) * 0.5
        cy = (y0 + y1) * 0.5
        cz = 0.0
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, cz))
        ob = bpy.context.active_object
        ob.name = f"MazeWall_{i:04d}"
        ob.dimensions = (sx, sy, sz)
        sit_on_ground(ob)
        if ob.data.materials:
            ob.data.materials[0] = mat
        else:
            ob.data.materials.append(mat)
        link_exclusive(ob, target_col)
        created.append(ob)
    return created

# ──────────────────────────────────────────────────────────────────────────────
# Pathfinding + metrics
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

def _count_turns_on_cells(cells):
    if len(cells) < 3: return 0
    def dir_of(a,b): return (b[0]-a[0], b[1]-a[1])
    turns=0; prev=dir_of(cells[0], cells[1])
    for i in range(1, len(cells)-1):
        d=dir_of(cells[i], cells[i+1])
        if d != prev: turns += 1
        prev = d
    return turns

def dijkstra_cost(g, start, goal, params, forbidden=None, clr=None):
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
            path = path[::-1]
            L = max(0, len(path)-1)
            T = _count_turns_on_cells(path)
            zig = T / max(1, L)
            smooth = 1.0 - zig
            return path, {"len":L, "turns":T, "zigzag":zig, "smooth":smooth}
        for rr,cc,dr,dc in neighbors_passages(g, r, c):
            if (rr,cc) in forbidden: continue
            wc = w_cost(pi,(dr,dc),rr,cc)
            ng = g_cost + wc
            ns = (rr,cc,(dr,dc))
            if ng < dist.get(ns, INF):
                dist[ns] = ng; prev[ns] = st
                heappush(pq, (ng + h(rr,cc,(dr,dc)), ng, ns))
    return [], {}

def greedy_explorative(g, start, goal, rng, trials, bias_turn=0.6, bias_open=0.6, bias_goal=-0.6, forbidden=None, clr=None):
    """Greedy scenic simple-path finder; favors openness & diversity (no repeats), still reaches goal."""
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

    best=None; bestM=None
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
        if path and path[-1]==goal:
            L = len(path)-1
            T = _count_turns_on_cells(path)
            zig = T / max(1, L)
            smooth = 1.0 - zig
            key = (L, -zig)  # prefer longer & less sawtooth
            if (best is None) or (key > bestM["key"]):
                best = path
                bestM = {"len":L, "turns":T, "zigzag":zig, "smooth":smooth, "key":key}
    if best: bestM.pop("key", None)
    return (best or []), (bestM or {})

# uniqueness / intersections
def jacc_similarity(A, B, ignore):
    a=set(map(tuple,A)) - ignore; b=set(map(tuple,B)) - ignore
    if not a and not b: return 1.0
    return len(a & b) / max(1, len(a | b))

def is_too_similar(candidate, existing, start, end, thresh):
    ignore={start,end}
    for ent in existing:
        if jacc_similarity(candidate, ent["cells"], ignore) >= thresh:
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
def build_purist(g, start, end, clr):
    return dijkstra_cost(g, start, end, {"step":1.0,"turn":0.0,"alley":0.0}, forbidden=None, clr=clr)

def build_explorative(g, start, end, rng, trials, clr):
    return greedy_explorative(g, start, end, rng, trials, bias_turn=0.6, bias_open=0.6, bias_goal=-0.6, forbidden=None, clr=clr)

# ──────────────────────────────────────────────────────────────────────────────
# Drawing helpers (tiles)
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

# ──────────────────────────────────────────────────────────────────────────────
# Properties (Purist + Explorative) + Build Mode
# ──────────────────────────────────────────────────────────────────────────────
class MMM_Props(PropertyGroup):
    # Size / randomness
    rows: IntProperty(name="Rows", default=22, min=5, soft_max=300)
    cols: IntProperty(name="Cols", default=34, min=5, soft_max=300)
    randomize: BoolProperty(name="Random Seed", default=True)
    seed: IntProperty(name="Seed", default=12345, min=0)

    # Geometry & materials
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

    build_wall_mode: EnumProperty(
        name="Wall Build Mode",
        items=[
            ('MERGED', "One Mesh (Fast)", "All walls in a single merged mesh"),
            ('SEPARATE', "Separate Cubes", "Each merged wall block becomes its own cube object"),
        ],
        default='MERGED'
    )

    # Path tiles
    tile_size: FloatProperty(name="Tile Size", default=0.90, min=0.1, max=1.5)
    tile_height: FloatProperty(name="Tile Height", default=0.05, min=0.005)
    tile_z_offset: FloatProperty(name="Tile Z Offset", default=0.03, min=0.0)
    start_color: FloatVectorProperty(name="Start Color", subtype='COLOR', size=4, default=(1.0,0.25,0.25,1.0))
    col_intersection: FloatVectorProperty(name="Intersection Color", subtype='COLOR', size=4, default=(0.7,0.2,0.2,1))

    # Styles (only two)
    use_purist: BoolProperty(name="Purist (Shortest)", default=True)
    col_purist: FloatVectorProperty(name="Purist Color", subtype='COLOR', size=4, default=(0.2,0.7,1.0,1))
    use_explorative: BoolProperty(name="Explorative (Scenic, No Repeats)", default=True)
    col_explorative: FloatVectorProperty(name="Explorative Color", subtype='COLOR', size=4, default=(1.0,0.85,0.2,1))
    explorative_trials: IntProperty(name="Explorative Trials", default=800, min=100, soft_max=6000)

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
    bl_label = "Generate Maze"
    bl_description = "Generate Prim's maze and classic walls (merged or separate cubes)."

    def execute(self, context):
        p = context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)

        maze_col = get_collection("maze")
        paths_col = get_collection("maze_paths")
        clear_collection(maze_col)
        clear_collection(paths_col)

        # Maze bitmap
        bitmap, H, W, s_open, e_open = prims_maze(p.rows, p.cols, rng)

        # Keep some dead-ends; carve tiny loops while preserving dead ends
        def count_passages_and_deadends(grid):
            rows, cols = len(grid), len(grid[0])
            passages=0; dead=0
            for r in range(1,rows-1):
                for c in range(1,cols-1):
                    if not grid[r][c]:
                        passages+=1; deg=0
                        for dr,dc in ((1,0),(0,1),(-1,0),(0,-1)):
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

        # Build classic walls (choose build mode)
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

        if p.build_wall_mode == 'MERGED':
            build_batched_prisms("MazeWalls", rects, heights, tuple(p.wall_color), maze_target, p.wall_mat_name)
        else:
            build_separate_cubes(rects, heights, tuple(p.wall_color), maze_target, p.wall_mat_name)

        # Ground plane
        if p.make_floor:
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
            floor=bpy.context.active_object; floor.name="BaseFloor"
            floor.dimensions=(total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
            sit_on_ground(floor)
            fm=ensure_mat(p.floor_mat_name, (0.14,0.14,0.16,1), rough=0.9)
            if floor.data.materials: floor.data.materials[0]=fm
            else: floor.data.materials.append(fm)
            link_exclusive(floor, maze_target)

        # Cache for path builder
        clr = clearance_score(bitmap)
        cache=_default_cache()
        cache.update({
            "bitmap": copy.deepcopy(bitmap), "rows": H, "cols": W,
            "start": start, "end": end,
            "off_x": off_x, "off_y": off_y, "cell_w": p.cell_w, "cell_h": p.cell_h,
            "paths": [], "clearance": clr,
            "metrics": [], "metrics_summary": {},
        })
        set_cache(context.scene, cache)

        self.report({'INFO'}, f"Generated {H}x{W}. Build Path Tiles when ready.")
        return {'FINISHED'}

class MMM_OT_BuildPaths(Operator):
    bl_idname = "mmm.build_paths"
    bl_label = "Build Path Tiles (Purist + Explorative)"
    bl_description = "Generate colored floor tiles for Purist and Explorative; avoids near-duplicates and controls intersections."

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
            if p.use_purist:      styles.append(("PURIST","DIJK", tuple(p.col_purist)))
            if p.use_explorative: styles.append(("EXPLORATIVE","MEAN", tuple(p.col_explorative)))
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

            def add_entry(tag, route, color, raw_metrics):
                nonlocal built, existing, new_entries, per_metrics_now
                entry={"key":tag, "cells":[tuple(rc) for rc in route], "color": color}
                new_entries.append(entry); existing.append(entry); built+=1
                per_metrics_now.append({"key":tag,
                                        "len": raw_metrics.get("len", len(route)-1),
                                        "turns": raw_metrics.get("turns", _count_turns_on_cells(route)),
                                        "zigzag": round(raw_metrics.get("zigzag", 0.0), 4),
                                        "smooth": round(raw_metrics.get("smooth", 0.0), 4),
                                        "ms": raw_metrics.get("ms")})

            def try_build_purist():
                t0=time.perf_counter()
                path, m = build_purist(bitmap, start, end, clr)
                t1=time.perf_counter()
                if not path: return
                m["ms"]=round((t1-t0)*1000.0,2)
                if p.enforce_unique and is_too_similar(path, existing, start, end, p.unique_jaccard_max):
                    return
                if p.enforce_overlap and (not overlap_ok(path, existing, p.min_shared_frac, p.max_shared_frac)):
                    return
                tag = "PURIST" if not (p.append_paths and cache["paths"]) else f"PURIST#{sum(1 for e in (existing+new_entries) if e['key'].startswith('PURIST'))+1}"
                add_entry(tag, path, tuple(p.col_purist), m)

            def try_build_explorative():
                t0=time.perf_counter()
                path, m = build_explorative(bitmap, start, end, rng, trials, clr)
                t1=time.perf_counter()
                if not path: return
                m["ms"]=round((t1-t0)*1000.0,2)
                if p.enforce_unique and is_too_similar(path, existing, start, end, p.unique_jaccard_max):
                    tries=reroutes
                    while tries>0:
                        tries-=1
                        core=[tuple(rc) for rc in path[1:-1]]
                        if not core: break
                        forbid=set(random.sample(core, max(1,int(0.15*len(core)))))
                        alt, mm = greedy_explorative(bitmap, start, end, rng, max(50,trials//2),
                                                     bias_turn=0.6, bias_open=0.6, bias_goal=-0.6,
                                                     forbidden=forbid, clr=clr)
                        if alt and not is_too_similar(alt, existing, start, end, p.unique_jaccard_max):
                            path, m = alt, mm; break
                if p.enforce_overlap and (not overlap_ok(path, existing, p.min_shared_frac, p.max_shared_frac)):
                    tries=reroutes
                    while tries>0:
                        tries-=1
                        worst_ent=None; best=0.0
                        for ent in existing:
                            f=_shared_fraction(path, ent["cells"])
                            if f>best: best=f; worst_ent=ent
                        forbid_pool = list(set(map(tuple,path[1:-1])) & set(map(tuple,worst_ent["cells"][1:-1]))) if worst_ent else []
                        forbid=set(random.sample(forbid_pool, max(1,int(0.2*len(forbid_pool))))) if forbid_pool else set()
                        alt, mm = greedy_explorative(bitmap, start, end, rng, max(50,trials//2),
                                                     bias_turn=0.6, bias_open=0.6, bias_goal=-0.6,
                                                     forbidden=forbid, clr=clr)
                        if alt and overlap_ok(alt, existing, p.min_shared_frac, p.max_shared_frac):
                            path, m = alt, mm; break
                if not path: return
                tag = "EXPLORATIVE" if not (p.append_paths and cache["paths"]) else f"EXPLORATIVE#{sum(1 for e in (existing+new_entries) if e['key'].startswith('EXPLORATIVE'))+1}"
                add_entry(tag, path, tuple(p.col_explorative), m)

            for name, solver, color in styles:
                if name=="PURIST": try_build_purist()
                elif name=="EXPLORATIVE": try_build_explorative()

            cache["paths"]=list(existing); set_cache(context.scene, cache)

            # Draw tiles & intersections
            clear_collection(get_collection("maze_paths"), name_prefixes=("Path_","Path_Intersections","StartTile"))
            sx,sy=rc_to_world(off_x,off_y,cell_w,cell_h,start)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sx,sy,0.0))
            st=bpy.context.active_object; st.name="StartTile"
            st.dimensions=(p.tile_size,p.tile_size,p.tile_height)
            sit_on_ground(st); st.location.z += p.tile_z_offset
            sm=ensure_mat("StartColor", tuple(p.start_color))
            if st.data.materials: st.data.materials[0]=sm
            else: st.data.materials.append(sm)
            link_exclusive(st, get_collection("maze_paths"))

            counts=Counter()
            for ent in cache["paths"]:
                for rc in ent["cells"]: counts[tuple(rc)]+=1
            overlap_cells={rc for rc,n in counts.items() if n>=2}
            geom=(cell_w,cell_h,off_x,off_y,p.tile_size,p.tile_height,p.tile_z_offset)
            for ent in cache["paths"]:
                draw_tiles_for_path(f"Path_{ent['key']}", ent["cells"], ent["color"], geom, skip_cells=overlap_cells)
            if overlap_cells:
                draw_tiles_for_cells("Path_Intersections", overlap_cells, tuple(p.col_intersection), geom)

            ms_total=0.0
            for m in per_metrics_now:
                if m.get("ms"): ms_total += (m["ms"] or 0.0)
            cache["metrics"]=per_metrics_now
            cache["metrics_summary"]={"total_paths":len(cache["paths"]), "intersections":len(overlap_cells), "ms_total":round(ms_total,2)}
            set_cache(context.scene, cache)

            self.report({'INFO'}, f"Built {len([e for e in new_entries])} new path(s). Total: {len(cache['paths'])}. Intersections: {len(overlap_cells)}")
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

# ── JSON grid exporter for Unreal ─────────────────────────────────────────────
class MMM_OT_ExportGridJSON(Operator):
    bl_idname = "mmm.export_grid_json"
    bl_label = "Export Grid JSON"
    bl_description = "Export the logical maze grid (rows/cols, cell size, origin, start/end, occupancy) for Unreal scoring."

    filepath: StringProperty(name="File Path", subtype='FILE_PATH', default="//maze_grid.json")

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = bpy.path.abspath("//maze_grid.json")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        cache = MODULE_CACHE.get(context.scene.as_pointer()) or MODULE_CACHE.get("__last__")
        if not cache or not cache.get("bitmap"):
            self.report({'WARNING'}, "Generate a maze first.")
            return {'CANCELLED'}

        bitmap = cache["bitmap"]
        rows, cols = cache["rows"], cache["cols"]
        start, end = cache["start"], cache["end"]
        cell_w, cell_h = cache["cell_w"], cache["cell_h"]
        off_x, off_y = cache["off_x"], cache["off_y"]

        origin_x, origin_y = rc_to_world(off_x, off_y, cell_w, cell_h, (0, 0))
        occ = []
        for r in range(rows):
            for c in range(cols):
                occ.append('1' if bitmap[r][c] else '0')
        data = {
            "version": "MMM-Grid-1",
            "rows": rows,
            "cols": cols,
            "cellSize": {"x": float(cell_w), "y": float(cell_h), "z": 0.0},
            "origin": {"x": float(origin_x), "y": float(origin_y), "z": 0.0},
            "start": {"r": int(start[0]), "c": int(start[1])},
            "end": {"r": int(end[0]), "c": int(end[1])},
            "occupancy": "".join(occ)
        }
        fp = bpy.path.abspath(self.filepath)

        # accept directory or filename
        if os.path.isdir(fp):
            fp = os.path.join(fp, "maze_grid.json")
        fp = bpy.path.ensure_ext(fp, ".json")
        parent_dir = os.path.dirname(fp)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to write JSON: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Exported grid JSON → {fp}")
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
        box.prop(p,"build_wall_mode")

        L.operator("mmm.generate", icon='MESH_CUBE', text="Generate Maze")

        L.separator()

        # Path Tiles
        box=L.box(); box.label(text="Path Tiles & Colors", icon='EVENT_T')
        row=box.row(align=True); row.prop(p,"tile_size"); row.prop(p,"tile_height"); row.prop(p,"tile_z_offset")
        row=box.row(align=True); row.prop(p,"start_color"); row.prop(p,"col_intersection")

        # Styles (only two)
        box=L.box(); box.label(text="Path Styles", icon='IPO_BEZIER')
        row=box.row(align=True); row.prop(p,"use_purist");      row.prop(p,"col_purist")
        row=box.row(align=True); row.prop(p,"use_explorative"); row.prop(p,"col_explorative")
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
        L.operator("mmm.build_paths", icon='MOD_BUILD', text="Build Path Tiles")
        L.operator("mmm.clear_paths", icon='TRASH', text="Clear Paths Only")

        box=L.box(); box.label(text="Export", icon='EXPORT')
        box.operator("mmm.export", icon='EXPORT', text="Export (OBJ/FBX/GLB)")
        box.operator("mmm.export_grid_json", icon='FILE_CACHE', text="Export Grid JSON")

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
        box=L.box(); box.label(text="Per-Path (Len/Turns/Zigzag/Smooth)", icon='SEQ_LUMA_WAVEFORM')
        for m in metrics:
            row=box.row(align=True)
            row.label(text=f"{m.get('key','?')}")
            row.label(text=f"L={m.get('len','–')}")
            row.label(text=f"T={m.get('turns','–')}")
            row.label(text=f"Z={m.get('zigzag','–')}")
            row.label(text=f"S={m.get('smooth','–')}")
            ms=m.get("ms"); row.label(text=("Time: {:.2f} ms".format(ms)) if ms is not None else "Time: —")

# ──────────────────────────────────────────────────────────────────────────────
# Register
# ──────────────────────────────────────────────────────────────────────────────
classes=(MMM_Props, MMM_OT_Generate, MMM_OT_BuildPaths, MMM_OT_ClearPaths, MMM_OT_Export, MMM_OT_ExportGridJSON, MMM_PT_Main, MMM_PT_Metrics)
def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.mmm_props = PointerProperty(type=MMM_Props)
def unregister():
    del bpy.types.Scene.mmm_props
    for c in reversed(classes): bpy.utils.unregister_class(c)
if __name__=="__main__":
    register()

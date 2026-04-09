bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G's brains (plus ChatGPT brawn)",
    "version": (2, 4, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A Prim's maze generator with distinct floor-path styles (Purist, Smooth, Experiential, Zigzag), intersections, and export.",
    "category": "Add Mesh",
}

import bpy, random, math, os, copy
from mathutils import Vector
from collections import deque, Counter
from heapq import heappush, heappop
from bpy.props import (IntProperty, FloatProperty, BoolProperty, FloatVectorProperty,
                       PointerProperty, StringProperty, EnumProperty)
from bpy.types import Operator, Panel, PropertyGroup

# ========= Module Runtime Cache (reliable across operators; not stored on Scene) =========
MODULE_CACHE = {}

def _default_cache():
    return {
        "bitmap": None,
        "rows": 0, "cols": 0,
        "start": None, "end": None,
        "off_x": 0.0, "off_y": 0.0,
        "cell_w": 1.0, "cell_h": 1.0,
        "paths": [],  # list of {"key","cells","color"}
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

# ===================== Dijkstra variants =====================
def dijkstra_cost(g, start, goal, params, forbidden=None):
    """Minimize: step + tau*turns + alley*tightness. 'forbidden' cells behave as walls."""
    R,C=len(g),len(g[0]); clr=clearance_score(g)
    forbidden = forbidden or set()
    step=params.get('step',1.0); tau=params.get('turn',0.0); alley=params.get('alley',0.0)
    INF=10**12; dist={}; prev={}; pq=[]
    s=(start[0],start[1],(0,0))
    dist[s]=0.0; heappush(pq,(0.0,s))
    def w_cost(pi,drdc,rr,cc):
        turn = tau if (pi!=(0,0) and pi!=drdc) else 0.0
        tight = clr[rr][cc]/4.0
        return max(0.0, step + turn + alley*tight)
    while pq:
        d, st = heappop(pq)
        if d!=dist.get(st,INF): continue
        r,c,pi=st
        if (r,c)==goal:
            path=[]; cur=st
            while cur in prev:
                (rr,cc,_), p = cur, prev[cur]
                path.append((rr,cc)); cur=p
            (rr,cc,_)=cur; path.append((rr,cc)); return path[::-1]
        for rr,cc,dr,dc in neighbors_passages(g,r,c):
            if (rr,cc) in forbidden: continue
            wc=w_cost(pi,(dr,dc),rr,cc); nd=d+wc
            ns=(rr,cc,(dr,dc))
            if nd<dist.get(ns,INF):
                dist[ns]=nd; prev[ns]=st; heappush(pq,(nd,ns))
    return []

# ===================== Greedy meander (long, self-avoiding) =====================
def greedy_meander(g, start, goal, rng, trials, bias_turn=0.0, bias_open=0.0, bias_goal=-0.7, forbidden=None):
    """Long simple path with reachability guard. bias_turn>0 favors turns; bias_open>0 favors open cells; bias_goal negative pushes away from goal early."""
    forbidden = forbidden or set()
    R,C=len(g),len(g[0]); clr=clearance_score(g)
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

# ===================== Uniqueness / similarity =====================
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

def ensure_unique_route(g, start, end, params, existing_entries, rng, max_tries, thresh):
    cand = dijkstra_cost(g, start, end, params, forbidden=None)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, start, end, thresh):
        return cand
    for _ in range(max_tries):
        core = [tuple(rc) for rc in cand[1:-1]]
        if not core: break
        forbid_k = max(1, int(len(core)*0.15))
        forbid = set(random.sample(core, min(forbid_k, len(core))))
        alt = dijkstra_cost(g, start, end, params, forbidden=forbid)
        if alt and not is_too_similar(alt, existing_entries, start, end, thresh):
            return alt
        if alt: cand = alt
    return []  # still too similar

def ensure_unique_route_meander(g, start, end, rng, trials, existing_entries, start_bias, thresh, max_tries):
    cand = greedy_meander(g, start, end, rng, trials, **start_bias, forbidden=None)
    if not cand: return []
    if not is_too_similar(cand, existing_entries, start, end, thresh):
        return cand
    for _ in range(max_tries):
        core = [tuple(rc) for rc in cand[1:-1]]
        if not core: break
        forbid_k = max(1, int(len(core)*0.15))
        forbid = set(random.sample(core, min(forbid_k, len(core))))
        alt = greedy_meander(g, start, end, rng, max(50, trials//2), **start_bias, forbidden=forbid)
        if alt and not is_too_similar(alt, existing_entries, start, end, thresh):
            return alt
        if alt: cand = alt
    return []  # still too similar

# ===================== Drawing =====================
def draw_tiles_for_path(name_prefix, path, color, geom, skip_cells):
    cell_w,cell_h,off_x,off_y,tile_xy,tile_h,tile_z = geom
    mat = ensure_mat(f"{name_prefix}_Mat", color)
    col = get_collection("maze_paths")
    for i, rc in enumerate(path):
        if tuple(rc) in skip_cells: continue
        x,y = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x,y,0.0))
        ob=bpy.context.active_object
        ob.name=f"{name_prefix}_{i:04d}"
        ob.dimensions=(tile_xy, tile_xy, tile_h)
        sit_on_ground(ob); ob.location.z += tile_z
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        link_exclusive(ob, col)

def draw_tiles_for_cells(name_prefix, cells, color, geom):
    cell_w,cell_h,off_x,off_y,tile_xy,tile_h,tile_z = geom
    mat = ensure_mat(f"{name_prefix}_Mat", color)
    col = get_collection("maze_paths")
    for i, rc in enumerate(sorted(cells)):
        x,y = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x,y,0.0))
        ob=bpy.context.active_object
        ob.name=f"{name_prefix}_{i:04d}"
        ob.dimensions=(tile_xy, tile_xy, tile_h)
        sit_on_ground(ob); ob.location.z += (tile_z + 0.002)
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        link_exclusive(ob, col)

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

    use_experiential: BoolProperty(name="Experiential", default=True, description="Long, scenic, self-avoiding route (greedy meander).")
    col_experiential: FloatVectorProperty(name="Experiential Color", subtype='COLOR', size=4, default=(1.0,0.85,0.2,1), description="Tile color for the Experiential path.")

    use_zigzag: BoolProperty(name="Zigzag", default=False, description="Maximize turns without repeats (expressive).")
    col_zigzag: FloatVectorProperty(name="Zigzag Color", subtype='COLOR', size=4, default=(1.0,0.5,0.9,1), description="Tile color for the Zigzag path.")

    experiential_trials: IntProperty(name="Greedy Trials", default=800, min=100, soft_max=6000, description="How hard the Experiential solver tries to find a long simple path (higher = longer runtime, potentially longer route).")

    # ---- Uniqueness guard
    enforce_unique: BoolProperty(name="Enforce Uniqueness", default=True, description="Avoid near-duplicate routes across styles.")
    unique_jaccard_max: FloatProperty(name="Max Similarity", default=0.85, min=0.5, max=0.99, description="If Jaccard similarity ≥ this threshold (ignoring endpoints), a path is considered too similar and will be rerouted or skipped.")
    unique_reroute_tries: IntProperty(name="Reroute Tries", default=8, min=0, max=50, description="How many alternate reroute attempts to try when a path is too similar.")

    # ---- Append behavior (visible after first build)
    append_paths: BoolProperty(name="Append New Paths", default=False, description="ON: add new styles on top of existing paths; OFF: replace overlays.")

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

        # Optional: carve a few loops while preserving dead-ends (keeps maze 'feel')
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

        # Walls
        wall_mat = ensure_mat(p.wall_mat_name, tuple(p.wall_color))
        blocks = merge_rectangles(bitmap, H, W)
        for (r,c,h,w) in blocks:
            sx, sy = w*p.cell_w, h*p.cell_h
            sz = p.height_max if p.uniform_height else random.uniform(p.height_min, p.height_max)
            cx = off_x + c*p.cell_w + (w-1)*p.cell_w/2
            cy = -(off_y + r*p.cell_h + (h-1)*p.cell_h/2)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, 0.0))
            ob=bpy.context.active_object; ob.name=f"MazeWall_{r}_{c}_{h}x{w}"
            ob.dimensions=(sx,sy,sz); sit_on_ground(ob)
            if ob.data.materials: ob.data.materials[0]=wall_mat
            else: ob.data.materials.append(wall_mat)
            link_exclusive(ob, get_collection("maze"))

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

        # Cache
        cache = _default_cache()
        cache.update({
            "bitmap": copy.deepcopy(bitmap),
            "rows": H, "cols": W,
            "start": start, "end": end,
            "off_x": off_x, "off_y": off_y,
            "cell_w": p.cell_w, "cell_h": p.cell_h,
            "paths": []
        })
        set_cache(context.scene, cache)

        self.report({'INFO'}, f"Maze {H}x{W} generated. Use 'Build Path Tiles (All Enabled)'.")
        return {'FINISHED'}

class MMM_OT_BuildPaths(Operator):
    bl_idname = "mmm.build_paths"
    bl_label = "Build Path Tiles (All Enabled)"
    bl_description = "Generate colored floor tiles for all enabled styles at once. Auto-computes intersections and enforces uniqueness."

    def execute(self, context):
        p=context.scene.mmm_props
        cache = get_cache(context.scene)
        if not cache or not cache.get("bitmap"):
            self.report({'WARNING'}, "Generate the maze first."); return {'CANCELLED'}

        bitmap = cache["bitmap"]
        start, end = tuple(cache["start"]), tuple(cache["end"])
        off_x, off_y = cache["off_x"], cache["off_y"]
        cell_w, cell_h = cache["cell_w"], cache["cell_h"]

        # Styles (4)
        styles=[]
        if p.use_purist:       styles.append(("PURIST","DIJK", dict(step=1.0, turn=0.0, alley=0.0), tuple(p.col_purist)))
        if p.use_smooth:       styles.append(("SMOOTH","DIJK", dict(step=1.0, turn=0.9, alley=0.0), tuple(p.col_smooth)))
        if p.use_experiential: styles.append(("EXPERIENTIAL","MEAN", dict(bias_turn=0.6, bias_open=0.6, bias_goal=-0.6), tuple(p.col_experiential)))
        if p.use_zigzag:       styles.append(("ZIGZAG","MEAN", dict(bias_turn=1.2, bias_open=0.0, bias_goal=-0.4), tuple(p.col_zigzag)))
        if not styles:
            self.report({'WARNING'}, "No styles enabled."); return {'CANCELLED'}

        rng = random.Random(None if p.randomize else p.seed)
        paths_col = get_collection("maze_paths")

        # Append behavior
        has_existing = isinstance(cache.get("paths"), list) and bool(cache["paths"])
        append = bool(p.append_paths and has_existing)

        existing = list(cache.get("paths", []))
        if not append:
            clear_collection(paths_col)
            existing = []
            cache["paths"] = []

        # Ensure StartTile
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

        # Build each style with uniqueness guard
        built=0; new_entries=[]
        for (name, solver, params, color) in styles:
            if solver=="DIJK":
                route = ensure_unique_route(bitmap, start, end, params, existing, rng,
                                            max_tries=p.unique_reroute_tries, thresh=p.unique_jaccard_max)
            else:
                route = ensure_unique_route_meander(bitmap, start, end, rng, p.experiential_trials,
                                                    existing, start_bias=params, thresh=p.unique_jaccard_max,
                                                    max_tries=p.unique_reroute_tries)
            if not route:
                print(f"[{name}] no distinct path found; skipped.")
                continue

            tag = f"{name}#{sum(1 for e in (existing+new_entries) if e['key'].startswith(name))+1}" if append else name
            entry={"key": tag, "cells": [tuple(rc) for rc in route], "color": color}
            new_entries.append(entry); existing.append(entry); built += 1

        cache["paths"] = list(existing)
        set_cache(context.scene, cache)

        # Redraw overlays
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

        self.report({'INFO'}, f"Built {built} new path(s). Total: {len(cache['paths'])}. Intersections: {len(overlap_cells)}")
        return {'FINISHED'}

class MMM_OT_ClearPaths(Operator):
    bl_idname = "mmm.clear_paths"
    bl_label = "Clear Paths Only"
    bl_description = "Removes all path tiles and resets the path cache. Keeps walls/floor intact."
    def execute(self, context):
        paths_col = get_collection("maze_paths")
        clear_collection(paths_col)
        cache = get_cache(context.scene) or _default_cache()
        cache["paths"] = []
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
        row=box.row(align=True); row.prop(p,"use_experiential");row.prop(p,"col_experiential")
        row=box.row(align=True); row.prop(p,"use_zigzag");      row.prop(p,"col_zigzag")
        box.prop(p,"experiential_trials")
        help_box = box.box()
        help_box.label(text="Style Guide:", icon='INFO')
        help_box.label(text="• Purist: shortest path by steps.")
        help_box.label(text="• Smooth: minimizes turns (flow).")
        help_box.label(text="• Experiential: long scenic route (self-avoiding).")
        help_box.label(text="• Zigzag: many turns, expressive pattern.")

        # ---- Uniqueness
        box=L.box(); box.label(text="Uniqueness Guard", icon='MOD_PHYSICS')
        box.label(text="Prevents near-duplicate routes. Higher Max Similarity allows more overlap; Reroute Tries tries to diversify.")
        row=box.row(align=True); row.prop(p,"enforce_unique"); row.prop(p,"unique_jaccard_max")
        row=box.row(align=True); row.prop(p,"unique_reroute_tries")

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

# ===================== Register =====================
classes=(MMM_Props, MMM_OT_Generate, MMM_OT_BuildPaths, MMM_OT_ClearPaths, MMM_OT_Export, MMM_PT_Main)
def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.mmm_props = PointerProperty(type=MMM_Props)
def unregister():
    del bpy.types.Scene.mmm_props
    for c in reversed(classes): bpy.utils.unregister_class(c)
if __name__=="__main__":
    register()

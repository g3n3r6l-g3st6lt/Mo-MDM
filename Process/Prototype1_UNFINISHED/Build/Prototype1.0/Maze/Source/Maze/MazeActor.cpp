#include "MazeActor.h"
#include "MazeGrid.h"
#include "MazeGameMode.h"
#include "MazeStart.h"
#include "MazeEnd.h"
#include "PivotalPoint.h"
#include "TeleportIn.h"
#include "TeleportOut.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "Kismet/GameplayStatics.h"

static FVector GetMeshSizeCm(const UStaticMesh* Mesh)
{
    if (!Mesh) return FVector(100.f,100.f,100.f);
    const FBoxSphereBounds B = Mesh->GetBounds();
    return B.BoxExtent*2.f;
}

AMazeActor::AMazeActor()
{
    WallsHISM = CreateDefaultSubobject<UHierarchicalInstancedStaticMeshComponent>(TEXT("WallsHISM"));
    FloorISM  = CreateDefaultSubobject<UInstancedStaticMeshComponent>(TEXT("FloorISM"));
    SetRootComponent(WallsHISM);
    FloorISM->SetupAttachment(RootComponent);
}

void AMazeActor::LoadFromAsset()
{
    if (ConfigAsset) Config = ConfigAsset->Config;
}

void AMazeActor::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);
    LoadFromAsset();
    Rebuild();
}

void AMazeActor::Rebuild()
{
    if (Config.Rows<=0 || Config.Cols<=0 || !Config.WallMesh || !Config.FloorMesh)
    {
        ClearInstances();
        return;
    }

    WallsHISM->SetStaticMesh(Config.WallMesh);
    FloorISM->SetStaticMesh(Config.FloorMesh);
    if (Config.WallMaterial)  WallsHISM->SetMaterial(0, Config.WallMaterial);
    if (Config.FloorMaterial) FloorISM->SetMaterial(0, Config.FloorMaterial);

    if (!Grid) Grid = NewObject<UMazeGrid>(this);
    Grid->Generate(Config);

    HeightRand.Initialize(Config.Seed*7919+17);

    if (Config.bAddEntranceExit)
    {
        ApplyEntranceExit();
    }

    ClearInstances();

    // Destroy any TeleportIn / TeleportOut actors from a previous build.
    if (UWorld* World = GetWorld())
    {
        TArray<AActor*> ToDestroy;

        TArray<AActor*> FoundIns;
        UGameplayStatics::GetAllActorsOfClass(World, ATeleportIn::StaticClass(), FoundIns);
        for (AActor* A : FoundIns)
        {
            if (A && A->GetOwner() == this)
            {
                ToDestroy.Add(A);
            }
        }

        TArray<AActor*> FoundOuts;
        UGameplayStatics::GetAllActorsOfClass(World, ATeleportOut::StaticClass(), FoundOuts);
        for (AActor* A : FoundOuts)
        {
            if (A && A->GetOwner() == this)
            {
                ToDestroy.Add(A);
            }
        }

        for (AActor* A : ToDestroy)
        {
            A->Destroy();
        }
    }

    BuildFloor();
    BuildWalls(Config.WallThickness);
    ComputeBranchStats();
    SpawnPivotalPoints();
    
    // Snap Start/End markers to their cells (editor & runtime) -- Snap Start/End
    {
        TArray<AActor*> Starts; UGameplayStatics::GetAllActorsOfClass(this, AMazeStart::StaticClass(), Starts);
        TArray<AActor*> Ends;   UGameplayStatics::GetAllActorsOfClass(this, AMazeEnd::StaticClass(), Ends);
        if (Starts.Num()>0)
        {
            const FVector SLoc = CellCenterToWorld(Config.EntranceCol, Config.EntranceRow);
            Starts[0]->SetActorLocation(SLoc);
        }
        if (Ends.Num()>0)
        {
            int32 ExitC = Config.ExitCol;
            int32 ExitR = Config.ExitRow;

            if (bSnapExitToLastCell || ExitC < 0)
            {
                ExitC = Config.Cols - 1;
            }
            if (bSnapExitToLastCell || ExitR < 0)
            {
                ExitR = Config.Rows - 1;
            }

            const FVector ELoc = CellCenterToWorld(ExitC, ExitR);
            Ends[0]->SetActorLocation(ELoc);
        }
    }


    if (AMazeGameMode* GM = GetWorld()->GetAuthGameMode<AMazeGameMode>())
    {
        GM->SetNumPivotalPointsTotal(PivotalPointCount);
    }
}


void AMazeActor::BeginPlay()
{
    Super::BeginPlay();

    UWorld* World = GetWorld();
    if (!World) return;

    // Optional runtime randomization of maze & teleports.
    if (bRandomizeOnBeginPlay)
    {
        ApplyRandomization();
    }

    // Count existing pivotal points in the level at runtime
    int32 LocalPivotalCount = 0;
    {
        TArray<AActor*> Pivots;
        UGameplayStatics::GetAllActorsOfClass(World, APivotalPoint::StaticClass(), Pivots);
        LocalPivotalCount = Pivots.Num();
    }

    if (AMazeGameMode* GM = World->GetAuthGameMode<AMazeGameMode>())
    {
        // Update the game mode with the total number of pivotal points
        GM->SetNumPivotalPointsTotal(LocalPivotalCount);

        // --- Automatic timer based on maze size & pivots ---
        const int32 NumCells = Config.Rows * Config.Cols;
        const int32 BaseFromCells  = FMath::RoundToInt(NumCells * 0.4f);          // ~0.4s per cell
        const int32 BaseFromPivots = (LocalPivotalCount > 0) ? (LocalPivotalCount * 2) : 0; // ~2s per pivot

        int32 BaseSeconds = BaseFromCells;
        if (BaseFromPivots > BaseSeconds)
        {
            BaseSeconds = BaseFromPivots;
        }

        const float Multiplier = 1.25f; // 25% buffer
        int32 FinalSeconds = FMath::RoundToInt(BaseSeconds * Multiplier);

        // Clamp to something reasonable
        FinalSeconds = FMath::Clamp(FinalSeconds, 20, 1800);

        GM->CountdownSeconds = FinalSeconds;
    }
}

void AMazeActor::ClearInstances()
{
    if (WallsHISM) WallsHISM->ClearInstances();
    if (FloorISM)  FloorISM->ClearInstances();
    for (auto& Ptr : SpawnedPivotalPoints) if (Ptr.IsValid()) Ptr->Destroy();
    SpawnedPivotalPoints.Reset();
    PivotalPointCount = 0;
}

FVector2D AMazeActor::GridOriginXY() const
{
    return FVector2D(-0.5f*Config.Cols*Config.CellSize, -0.5f*Config.Rows*Config.CellSize);
}

FVector AMazeActor::CellCenterToWorld(int32 C, int32 R) const
{
    const FVector2D O = GridOriginXY();
    return FVector(O.X + (C+0.5f)*Config.CellSize, O.Y + (R+0.5f)*Config.CellSize, GetActorLocation().Z);
}


void AMazeActor::GetMazeWorldBounds2D(FVector2D& OutMin, FVector2D& OutMax) const
{
    const FVector2D Origin = GridOriginXY();
    const float Width  = Config.Cols * Config.CellSize;
    const float Height = Config.Rows * Config.CellSize;

    const FVector ActorLoc = GetActorLocation();

    OutMin = FVector2D(ActorLoc.X + Origin.X, ActorLoc.Y + Origin.Y);
    OutMax = FVector2D(ActorLoc.X + Origin.X + Width, ActorLoc.Y + Origin.Y + Height);
}

void AMazeActor::BuildFloor()
{
    const FVector2D O = GridOriginXY();
    const FVector CellSize3(Config.CellSize, Config.CellSize, 1.f);
    const FVector2D Step(Config.CellSize, Config.CellSize);
    const FVector FloorScale = CellSize3 / GetMeshSizeCm(Config.FloorMesh);

    for (int32 R=0; R<Config.Rows; ++R)
    {
        for (int32 C=0; C<Config.Cols; ++C)
        {
            const FVector Loc(O.X + (C+0.5f)*Step.X, O.Y + (R+0.5f)*Step.Y, GetActorLocation().Z);
            const FTransform T(FRotator::ZeroRotator, Loc, FloorScale);
            FloorISM->AddInstance(T);
        }
    }
}

void AMazeActor::BuildWalls(float Thick)
{
    if (!Grid || !WallsHISM) return;

    WallsHISM->ClearInstances();

    const FVector2D O = GridOriginXY();
    const FVector2D Step(Config.CellSize, Config.CellSize);
    const FVector2D Half = Step * 0.5f;
    const FVector WallScaleX = FVector(Config.CellSize, Thick, Config.WallHeight) / GetMeshSizeCm(Config.WallMesh);
    const FVector WallScaleY = FVector(Thick, Config.CellSize, Config.WallHeight) / GetMeshSizeCm(Config.WallMesh);

    TArray<FTransform> WallTransforms;

    // Collect all wall segment transforms (like before).
    for (int32 R = 0; R < Config.Rows; ++R)
    {
        for (int32 C = 0; C < Config.Cols; ++C)
        {
            const FMazeCell& Cell = Grid->Cells[Grid->Index(C, R)];
            const FVector Base(O.X + C * Step.X, O.Y + R * Step.Y, GetActorLocation().Z);

            if (Cell.N) // north wall
            {
                const FVector Loc(Base.X + Half.X, Base.Y, Base.Z);
                const FTransform T(FRotator::ZeroRotator, Loc, WallScaleX);
                WallTransforms.Add(T);
            }
            if (Cell.E) // east
            {
                const FVector Loc(Base.X + Step.X, Base.Y + Half.Y, Base.Z);
                const FTransform T(FRotator::ZeroRotator, Loc, WallScaleY);
                WallTransforms.Add(T);
            }
            if (Cell.S) // south
            {
                const FVector Loc(Base.X + Half.X, Base.Y + Step.Y, Base.Z);
                const FTransform T(FRotator::ZeroRotator, Loc, WallScaleX);
                WallTransforms.Add(T);
            }
            if (Cell.W) // west
            {
                const FVector Loc(Base.X, Base.Y + Half.Y, Base.Z);
                const FTransform T(FRotator::ZeroRotator, Loc, WallScaleY);
                WallTransforms.Add(T);
            }
        }
    }

    // Edge filter: avoid placing teleporters on outer walls (to avoid falling off).
    const float MinX = O.X + Step.X;
    const float MaxX = O.X + (Config.Cols - 1) * Step.X;
    const float MinY = O.Y + Step.Y;
    const float MaxY = O.Y + (Config.Rows - 1) * Step.Y;

    TArray<FTransform> InternalWalls;
    for (const FTransform& T : WallTransforms)
    {
        const FVector L = T.GetLocation();
        if (L.X <= MinX || L.X >= MaxX || L.Y <= MinY || L.Y >= MaxY)
        {
            continue;
        }
        InternalWalls.Add(T);
    }

    // Choose TeleportIn/TeleportOut positions.
    TArray<FTransform> InTransforms;
    TArray<FTransform> OutTransforms;

    const int32 TotalDesired = NumTeleportIn + NumTeleportOut;
    if (TotalDesired > 0 && InternalWalls.Num() > 0 &&
        TeleportInClass && TeleportOutClass)
    {
        FRandomStream Rng(Config.Seed * 9871 + 77);
        TArray<FTransform> Candidates = InternalWalls;

        TArray<FTransform> Chosen;
        int32 Spawned = 0;

        while (Candidates.Num() > 0 && Spawned < TotalDesired)
        {
            const int32 Index = Rng.RandRange(0, Candidates.Num() - 1);
            const FTransform Candidate = Candidates[Index];
            Candidates.RemoveAtSwap(Index, 1);

            bool bFarEnough = true;
            const FVector Loc = Candidate.GetLocation();
            for (const FTransform& Existing : Chosen)
            {
                if (FVector::Dist2D(Loc, Existing.GetLocation()) < MinTeleporterDistance)
                {
                    bFarEnough = false;
                    break;
                }
            }

            if (!bFarEnough)
            {
                continue;
            }

            Chosen.Add(Candidate);
            ++Spawned;
        }

        const int32 NumInClamped  = FMath::Clamp(NumTeleportIn, 0, Chosen.Num());
        const int32 NumOutClamped = FMath::Clamp(NumTeleportOut, 0, Chosen.Num() - NumInClamped);

        for (int32 i = 0; i < NumInClamped; ++i)
        {
            InTransforms.Add(Chosen[i]);
        }
        for (int32 i = 0; i < NumOutClamped; ++i)
        {
            OutTransforms.Add(Chosen[NumInClamped + i]);
        }
    }

    // Build a set of positions where we should NOT spawn normal walls (because teleporters will go there).
    TArray<FVector> TeleLocs;
    for (const FTransform& T : InTransforms)  TeleLocs.Add(T.GetLocation());
    for (const FTransform& T : OutTransforms) TeleLocs.Add(T.GetLocation());

    // Spawn normal wall instances (skipping teleporter positions).
    for (const FTransform& T : WallTransforms)
    {
        bool bSkip = false;
        for (const FVector& TL : TeleLocs)
        {
            if (FVector::Dist2D(T.GetLocation(), TL) < 1.f)
            {
                bSkip = true;
                break;
            }
        }

        if (!bSkip)
        {
            WallsHISM->AddInstance(T);
        }
    }

    // Spawn TeleportIn / TeleportOut actors at the chosen locations.
    UWorld* World = GetWorld();
    if (World)
    {
        FActorSpawnParameters SP;
        SP.Owner = this;

        for (const FTransform& T : InTransforms)
        {
            World->SpawnActor<ATeleportIn>(
                TeleportInClass,
                T.GetLocation(),
                T.GetRotation().Rotator(),
                SP);
        }

        for (const FTransform& T : OutTransforms)
        {
            World->SpawnActor<ATeleportOut>(
                TeleportOutClass,
                T.GetLocation(),
                T.GetRotation().Rotator(),
                SP);
        }
    }
}


void AMazeActor::ApplyEntranceExit()
{
    // Entrance/exit carving is already handled by generation or is disabled; noop for now.
}

void AMazeActor::SpawnPivotalPoints()
{
    UWorld* World = GetWorld();
    if (!World || !Grid || !PivotalPointClass)
    {
        PivotalPointCount = 0;
        return;
    }

    SpawnedPivotalPoints.Reset();
    PivotalPointCount = 0;

    int32 ExitC = Config.ExitCol;
    int32 ExitR = Config.ExitRow;

    if (bSnapExitToLastCell || ExitC < 0)
    {
        ExitC = Config.Cols - 1;
    }
    if (bSnapExitToLastCell || ExitR < 0)
    {
        ExitR = Config.Rows - 1;
    }

    for (int32 R = 0; R < Config.Rows; ++R)
    {
        for (int32 C = 0; C < Config.Cols; ++C)
        {
            // Only consider strong junctions: 4 or more open sides.
            const int32 OpenSides = Grid->CountOpenSides(C, R);
            if (OpenSides < 3)
            {
                continue;
            }

            // Skip entrance / exit cells.
            if ((C == Config.EntranceCol && R == Config.EntranceRow) ||
                (C == ExitC && R == ExitR))
            {
                continue;
            }

            const FVector Loc = CellCenterToWorld(C, R);
            FActorSpawnParameters SP;
            SP.Owner = this;

            APivotalPoint* PP = World->SpawnActor<APivotalPoint>(
                PivotalPointClass,
                Loc,
                FRotator::ZeroRotator,
                SP);

            if (PP)
            {
                SpawnedPivotalPoints.Add(PP);
                ++PivotalPointCount;
            }
        }
    }
}


void AMazeActor::ApplyRandomization()
{
    // Determine an effective seed for this randomization pass.
    int32 EffectiveSeed = Config.Seed;
    if (bUseRandomSeedEachPlay)
    {
        // Pick a new seed in the requested range and also store it back into Config.Seed
        if (RandomSeedMax >= RandomSeedMin)
        {
            EffectiveSeed = FMath::RandRange(RandomSeedMin, RandomSeedMax);
        }
        else
        {
            EffectiveSeed = FMath::Rand();
        }
        Config.Seed = EffectiveSeed;
    }

    FRandomStream Rng(EffectiveSeed);

    // Randomize core maze dimensions if the ranges are valid.
    if (MinRandomRows > 1 && MaxRandomRows >= MinRandomRows)
    {
        const int32 NewRows = Rng.RandRange(MinRandomRows, MaxRandomRows);
        Config.Rows = FMath::Clamp(NewRows, 2, 1024);
    }
    if (MinRandomCols > 1 && MaxRandomCols >= MinRandomCols)
    {
        const int32 NewCols = Rng.RandRange(MinRandomCols, MaxRandomCols);
        Config.Cols = FMath::Clamp(NewCols, 2, 1024);
    }

    // Randomize number of teleporters (in/out) if ranges are valid.
    if (MinRandomTeleportIn >= 0 && MaxRandomTeleportIn >= MinRandomTeleportIn)
    {
        NumTeleportIn = FMath::Max(0, Rng.RandRange(MinRandomTeleportIn, MaxRandomTeleportIn));
    }
    if (MinRandomTeleportOut >= 0 && MaxRandomTeleportOut >= MinRandomTeleportOut)
    {
        NumTeleportOut = FMath::Max(0, Rng.RandRange(MinRandomTeleportOut, MaxRandomTeleportOut));
    }

    // Randomize entrance / exit sides if requested.
    auto RandSide = [&Rng]() -> EMazeSide
    {
        const int32 Index = Rng.RandRange(0, 3);
        switch (Index)
        {
        case 0: return EMazeSide::North;
        case 1: return EMazeSide::East;
        case 2: return EMazeSide::South;
        default: return EMazeSide::West;
        }
    };

    if (bRandomizeEntranceSide)
    {
        Config.EntranceSide = RandSide();
    }
    if (bRandomizeExitSide)
    {
        Config.ExitSide = RandSide();
    }

    // After mutating config, rebuild the maze (walls, floor, pivots, teleporters).
    Rebuild();
}

void AMazeActor::PreviewRandomization()
{
#if WITH_EDITOR
    ApplyRandomization();
#endif
}


void AMazeActor::ComputeBranchStats()
{
    BranchCount = ComputeBranchCountInternal();
}

int32 AMazeActor::ComputeBranchCountInternal() const
{
    if (!Grid)
    {
        return 0;
    }

    int32 Count = 0;
    for (int32 R = 0; R < Config.Rows; ++R)
    {
        for (int32 C = 0; C < Config.Cols; ++C)
        {
            if (Grid->IsJunction(C, R))
            {
                ++Count;
            }
        }
    }
    return Count;
}

TArray<FVector> AMazeActor::GetStartToEndPathWorld() const
{
    TArray<FVector> Result;

    if (!Grid)
    {
        return Result;
    }

    const int32 StartC = Config.EntranceCol;
    const int32 StartR = Config.EntranceRow;

    int32 ExitC  = Config.ExitCol;
    int32 ExitR  = Config.ExitRow;
    if (bSnapExitToLastCell || ExitC < 0)
    {
        ExitC = Config.Cols - 1;
    }
    if (bSnapExitToLastCell || ExitR < 0)
    {
        ExitR = Config.Rows - 1;
    }

    const TArray<FIntPoint> Path = Grid->FindPathBFS(FIntPoint(StartC, StartR), FIntPoint(ExitC, ExitR));

    for (const FIntPoint& P : Path)
    {
        Result.Add(CellCenterToWorld(P.X, P.Y));
    }

    return Result;
}

#if WITH_EDITOR
void AMazeActor::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
    Super::PostEditChangeProperty(PropertyChangedEvent);
    Rebuild();
}
#endif


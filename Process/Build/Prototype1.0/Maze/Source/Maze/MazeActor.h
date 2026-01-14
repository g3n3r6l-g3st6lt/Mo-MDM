#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "MazeTypes.h"
#include "MazeActor.generated.h"

class UMazeGrid;
class UMazeConfigData;
class APivotalPoint;
class ATeleportIn;
class ATeleportOut;

UCLASS()
class MAZE_API AMazeActor : public AActor
{
    GENERATED_BODY()
public:
    AMazeActor();

    UFUNCTION(BlueprintCallable, Category="Maze")
    void LoadFromAsset();

    UFUNCTION(BlueprintCallable, Category="Maze")
    void Rebuild();

    UFUNCTION(BlueprintCallable, Category="Maze")
    FVector CellCenterToWorld(int32 C, int32 R) const;

    UFUNCTION(CallInEditor, BlueprintCallable, Category="Maze|Analysis")
    void ComputeBranchStats();

    UPROPERTY(EditAnywhere, Category="Maze|Pivotal")
    TSubclassOf<APivotalPoint> PivotalPointClass;

    UPROPERTY(VisibleAnywhere, Category="Maze|Pivotal")
    int32 PivotalPointCount = 0;
    
    UFUNCTION(BlueprintCallable, Category="Maze|Path")
    TArray<FVector> GetStartToEndPathWorld() const;

protected:
    virtual void OnConstruction(const FTransform& Transform) override;
    virtual void BeginPlay() override;

    UPROPERTY(VisibleAnywhere, Category="Maze|Meshes")
    UHierarchicalInstancedStaticMeshComponent* WallsHISM;

    UPROPERTY(VisibleAnywhere, Category="Maze|Meshes")
    UInstancedStaticMeshComponent* FloorISM;

    UPROPERTY(VisibleAnywhere, Category="Maze|Data")
    UMazeGrid* Grid;

    UPROPERTY(EditAnywhere, Category="Maze|Data")
    UMazeConfigData* ConfigAsset;

    UPROPERTY(EditAnywhere, Category="Maze|Config")
    FMazeConfig Config;
    UPROPERTY(EditAnywhere, Category="Maze|Config")
    bool bSnapExitToLastCell = false;

    // If true, randomize maze dimensions, teleporter counts, and entrance/exit sides at BeginPlay.
    UPROPERTY(EditAnywhere, Category="Maze|Random")
    bool bRandomizeOnBeginPlay = false;

    // Random row/column ranges (inclusive) when randomization is enabled.
    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MinRandomRows = 5;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MaxRandomRows = 20;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MinRandomCols = 5;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MaxRandomCols = 20;

    // Random TeleportIn / TeleportOut counts when randomization is enabled.
    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MinRandomTeleportIn = 0;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MaxRandomTeleportIn = 4;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MinRandomTeleportOut = 0;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 MaxRandomTeleportOut = 4;

    // Randomize entrance/exit sides (East/West/North/South) when randomization is enabled.
    UPROPERTY(EditAnywhere, Category="Maze|Random")
    bool bRandomizeEntranceSide = true;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    bool bRandomizeExitSide = true;


    // If true, a new random seed will be chosen each play (and stored in Config.Seed).
    UPROPERTY(EditAnywhere, Category="Maze|Random")
    bool bUseRandomSeedEachPlay = false;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 RandomSeedMin = 0;

    UPROPERTY(EditAnywhere, Category="Maze|Random")
    int32 RandomSeedMax = 1000000;


    UPROPERTY()
    TArray<TWeakObjectPtr<APivotalPoint>> SpawnedPivotalPoints;

    void ClearInstances();
    FVector2D GridOriginXY() const;
    void BuildFloor();
    void BuildWalls(float EffectiveWallThickness);
    void ApplyEntranceExit();
    bool OpenBoundary(int32 C, int32 R, EMazeSide Side);
    void SpawnPivotalPoints();
    void ApplyRandomization();

#if WITH_EDITOR
    virtual void PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent) override;
#endif

private:
    FRandomStream HeightRand;
    // Teleporters: individual IN and OUT wall cells that replace normal walls.
UPROPERTY(EditAnywhere, Category="Maze|Teleport")
TSubclassOf<class ATeleportIn> TeleportInClass;

UPROPERTY(EditAnywhere, Category="Maze|Teleport")
TSubclassOf<class ATeleportOut> TeleportOutClass;

UPROPERTY(EditAnywhere, Category="Maze|Teleport")
int32 NumTeleportIn = 0;

UPROPERTY(EditAnywhere, Category="Maze|Teleport")
int32 NumTeleportOut = 0;

// Minimum 2D distance between any two teleporters (to avoid clustering).
UPROPERTY(EditAnywhere, Category="Maze|Teleport")
float MinTeleporterDistance = 800.f;

    
public:

    UFUNCTION(CallInEditor, Category="Maze|Random")
    void PreviewRandomization();

UPROPERTY(VisibleAnywhere, Category="Maze|Analysis")
    int32 BranchCount = 0;
    int32 ComputeBranchCountInternal() const;
    UFUNCTION(BlueprintCallable, Category="Maze|Analysis")
    void GetMazeWorldBounds2D(FVector2D& OutMin, FVector2D& OutMax) const;
};

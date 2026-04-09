#pragma once
#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "MazeTypes.generated.h"

UENUM(BlueprintType)
enum class EMazeSide : uint8 { North, East, South, West };

UENUM(BlueprintType)
enum class EMazeGenAlgo : uint8 { DFS, Prims };

USTRUCT(BlueprintType)
struct FMazeCell
{
    GENERATED_BODY()
    UPROPERTY() bool N=true, E=true, S=true, W=true;
    UPROPERTY() bool Visited=false;
};

USTRUCT(BlueprintType)
struct FMazeConfig
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 Rows=10;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 Cols=10;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 Seed=1337;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) float CellSize=200.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) float WallThickness=20.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) float WallHeight=200.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) TObjectPtr<UStaticMesh> WallMesh=nullptr;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) TObjectPtr<UStaticMesh> FloorMesh=nullptr;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) TObjectPtr<UMaterialInterface> WallMaterial=nullptr;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) TObjectPtr<UMaterialInterface> FloorMaterial=nullptr;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) bool bAddOuterWalls=true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) bool bAddEntranceExit=true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 EntranceCol=0;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 EntranceRow=0;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 ExitCol=-1;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) int32 ExitRow=-1;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) EMazeSide EntranceSide=EMazeSide::West;
    UPROPERTY(EditAnywhere, BlueprintReadWrite) EMazeSide ExitSide=EMazeSide::East;
};

UCLASS(BlueprintType)
class UMazeConfigData : public UDataAsset
{
    GENERATED_BODY()
public:
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FMazeConfig Config;
};
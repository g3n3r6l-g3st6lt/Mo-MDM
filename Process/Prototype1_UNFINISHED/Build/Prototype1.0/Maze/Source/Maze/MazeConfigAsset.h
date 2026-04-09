#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "MazeTypes.h"
#include "MazeConfigAsset.generated.h"

class UMazeChaseBrain;

/**
 * Designer-facing asset that configures a maze "preset" or biome.
 * Wraps FMazeConfig and adds high-level behavior rules.
 */
USTRUCT(BlueprintType)
struct FMazeTeleporterRuleSettings
{
    GENERATED_BODY()

    /** Minimum number of TeleportIn actors to spawn in the maze. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Teleporter Rules")
    int32 MinTeleporters = 0;

    /** Maximum number of TeleportIn actors to spawn in the maze. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Teleporter Rules")
    int32 MaxTeleporters = 0;

    /** If true, avoid placing teleporters in the end cell and its neighbors. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Teleporter Rules")
    bool bDisallowNearEnd = true;

    /** If true, avoid placing teleporters in immediately neighboring cells to each other. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Teleporter Rules")
    bool bDisallowNeighboringEntries = true;
};

/**
 * Asset describing a maze configuration plus behavior rules such as teleporters, pivots and chase style.
 * This is intended to be the single source of truth for "how this maze behaves".
 */
UCLASS(BlueprintType)
class MAZE_API UMazeConfigAsset : public UDataAsset
{
    GENERATED_BODY()

public:
    /** Base maze generation parameters (size, seed, entrance/exit, meshes, etc.). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Maze")
    FMazeConfig BaseConfig;

    /** Rules for TeleportIn/TeleportOut placement. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Maze|Teleporters")
    FMazeTeleporterRuleSettings TeleporterRules;

    /** Rules for pivotal point placement. Mirrors teleporter rules, but applied to APivotalPoint actors. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Maze|PivotalPoints")
    FMazeTeleporterRuleSettings PivotalRules;

    /** Chase brain class used by MazeEnd for this maze configuration. */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Maze|Chase")
    TSubclassOf<UMazeChaseBrain> ChaseBrainClass;

    /** Returns a runtime FMazeConfig built from this asset. */
    FMazeConfig ToRuntimeConfig() const;
};

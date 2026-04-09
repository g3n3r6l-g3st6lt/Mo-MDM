#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "MazeStatsManagerSubsystem.generated.h"

/** High-level summary of a single maze run. */
USTRUCT(BlueprintType)
struct FMazeRunSummary
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Maze|Stats")
    int32 Steps = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Maze|Stats")
    int32 Turns = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Maze|Stats")
    float ElapsedTime = 0.f;

    UPROPERTY(BlueprintReadOnly, Category = "Maze|Stats")
    bool bCompleted = false;
};

/**
 * Central location for tracking maze run statistics. Intended to support
 * save/load and referencing stats from multiple systems (HUD, UI, analytics).
 */
UCLASS()
class MAZE_API UMazeStatsManagerSubsystem : public UGameInstanceSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category = "Maze|Stats")
    void StartRun();

    UFUNCTION(BlueprintCallable, Category = "Maze|Stats")
    void FinishRun(bool bInCompleted);

    UFUNCTION(BlueprintCallable, Category = "Maze|Stats")
    void NotifyStepTaken();

    UFUNCTION(BlueprintCallable, Category = "Maze|Stats")
    void NotifyTurnMade();

    UFUNCTION(BlueprintCallable, Category = "Maze|Stats")
    void TickRun(float DeltaSeconds);

    UFUNCTION(BlueprintCallable, Category = "Maze|Stats")
    FMazeRunSummary GetCurrentSummary() const;

private:
    FMazeRunSummary CurrentRun;
    bool bRunActive = false;
};

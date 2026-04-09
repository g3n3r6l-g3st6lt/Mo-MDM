#pragma once
#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "MazeGameMode.generated.h"

class AMazeStart;
class AMazeEnd;
class APawn;

UCLASS(minimalapi)
class AMazeGameMode : public AGameModeBase
{
    GENERATED_BODY()

public:
    AMazeGameMode();
    virtual void BeginPlay() override;

    UFUNCTION(BlueprintCallable)
    void NotifyPlayerReachedGoal(AActor* ReachedActor);

    // Called when the moving maze end reaches the maze start without the player.
    UFUNCTION(BlueprintCallable)
    void NotifyEndReachedStart();

    // --- Countdown (0 disables) ---
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Maze|Rules")
    int32 CountdownSeconds = 0;

    UFUNCTION(BlueprintCallable, Category="Maze|Rules")
    float GetTimeRemaining() const;

    UFUNCTION(BlueprintCallable, Category="Maze|Rules")
    bool IsTimeExpired() const;

    UFUNCTION(BlueprintCallable)
    bool GetHasFinished() const { return bHasFinished; }

    UFUNCTION(BlueprintCallable)
    const FVector& GetStartLocation() const { return StartLocation; }

    UFUNCTION(BlueprintCallable)
    const FVector& GetEndLocation() const { return EndLocation; }

    UFUNCTION(BlueprintCallable)
    int32 GetNumPivotalPointsTotal() const { return NumPivotalPointsTotal; }

    UFUNCTION(BlueprintCallable)
    int32 GetNumPivotalPointsActivated() const { return NumPivotalPointsActivated; }

    UFUNCTION(BlueprintCallable)
    void SetNumPivotalPointsTotal(int32 InTotal) { NumPivotalPointsTotal = InTotal; }

    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    int32 GetFinalStepCount() const { return FinalStepCount; }

    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    int32 GetFinalTurnCount() const { return FinalTurnCount; }

    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    int32 GetFinalPivotalPointsActivated() const { return FinalPivotalPointsActivated; }

    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    float GetFinalTimeRemaining() const { return FinalTimeRemaining; }

    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    float GetOvertimeSeconds() const { return OvertimeSeconds; }

    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    bool GetStatsFrozen() const { return bStatsFrozen; }

    UFUNCTION(BlueprintCallable, Category="Maze|Status")
    FName GetFinishStatus() const { return FinishStatus; }

    UFUNCTION(BlueprintCallable)
    void IncrementPivotalPointsActivated();

protected:
    void PlacePlayerAtStart();

private:
    void FreezeStatsAndFinish(FName InFinishStatus, APawn* InstigatorPawn);

    float GameStartTime = 0.f;

    UPROPERTY()
    AMazeStart* MazeStartActor = nullptr;

    UPROPERTY()
    AMazeEnd* MazeEndActor = nullptr;

    UPROPERTY()
    bool bHasFinished = false;

    FVector StartLocation = FVector::ZeroVector;
    FVector EndLocation   = FVector::ZeroVector;

    UPROPERTY(VisibleAnywhere, Category="Maze")
    int32 NumPathsAvailable = 0;

    int32 NumPivotalPointsTotal = 0;
    int32 NumPivotalPointsActivated = 0;

    // Frozen stats at the moment the run ends.
    UPROPERTY(VisibleAnywhere, Category="Maze|Stats")
    int32 FinalStepCount = 0;

    UPROPERTY(VisibleAnywhere, Category="Maze|Stats")
    int32 FinalTurnCount = 0;

    UPROPERTY(VisibleAnywhere, Category="Maze|Stats")
    int32 FinalPivotalPointsActivated = 0;

    UPROPERTY(VisibleAnywhere, Category="Maze|Stats")
    float FinalTimeRemaining = TNumericLimits<float>::Max();

    UPROPERTY(VisibleAnywhere, Category="Maze|Stats")
    float OvertimeSeconds = 0.f;

    UPROPERTY(VisibleAnywhere, Category="Maze|Stats")
    bool bStatsFrozen = false;

    UPROPERTY(VisibleAnywhere, Category="Maze|Status")
    FName FinishStatus = NAME_None;
};

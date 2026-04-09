#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "InputActionValue.h"
#include "MazePlayerController.generated.h"

class UInputMappingContext;
class UInputAction;
class UEnhancedInputComponent;
class UEnhancedInputLocalPlayerSubsystem;

UCLASS()
class AMazePlayerController : public APlayerController
{
    GENERATED_BODY()

public:
    AMazePlayerController();

    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    virtual void SetupInputComponent() override;

    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    int32 GetStepCount() const { return StepCount; }
    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    int32 GetTurnCount() const { return TurnCount; }
    UFUNCTION(BlueprintCallable, Category="Maze|Stats")
    void SetCountersFrozen(bool bFrozen) { bCountersFrozen = bFrozen; }


    float GetMoveX() const { return MoveX; }
    float GetMoveY() const { return MoveY; }

protected:
    void HandleMoveForward(const FInputActionValue& Value);
    void HandleMoveForward_Stopped(const FInputActionValue& Value);

    void HandleMoveRight(const FInputActionValue& Value);
    void HandleMoveRight_Stopped(const FInputActionValue& Value);

private:
    // latest intended input
    float MoveX; // left/right
    float MoveY; // forward/back

    // step counting timer
    float StepTimer;
    UPROPERTY(EditAnywhere, Category="Stats")
    float TimePerHalfStep;

    int32 StepCount;

    // turn counting
    FVector2D PrevDirNorm;
    bool bHasPrevDir;
    int32 TurnCount;
    bool bCountersFrozen = false;

public:
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Input")
    UInputMappingContext* MappingContext;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Input")
    UInputAction* IA_MoveForward;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Input")
    UInputAction* IA_MoveRight;
};

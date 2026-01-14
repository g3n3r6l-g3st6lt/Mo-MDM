#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "MazeCharacter.generated.h"

class USpringArmComponent;
class UCameraComponent;

UCLASS()
class AMazeCharacter : public ACharacter
{
    GENERATED_BODY()

public:
    AMazeCharacter();

    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;

    UFUNCTION(BlueprintCallable, Category="Maze|Teleport")
    float GetLastTeleportTime() const { return LastTeleportTime; }

    UFUNCTION(BlueprintCallable, Category="Maze|Teleport")
    void SetLastTeleportTime(float InTime) { LastTeleportTime = InTime; }

protected:
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Camera")
    USpringArmComponent* CameraBoom;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Camera")
    UCameraComponent* FollowCamera;

    UPROPERTY(VisibleAnywhere, BlueprintReadWrite, Category="Maze|Teleport")
    float LastTeleportTime = -1000.f;
};

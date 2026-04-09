#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MazeEnd.generated.h"

class USphereComponent;
class UStaticMeshComponent;
class UStaticMesh;
class UMaterialInterface;

UCLASS()
class MAZE_API AMazeEnd : public AActor
{
    GENERATED_BODY()
public:
    AMazeEnd();
    virtual void OnConstruction(const FTransform& Transform) override;
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;

protected:
    UPROPERTY(VisibleAnywhere, Category="Components")
    USceneComponent* Root;

    UPROPERTY(VisibleAnywhere, Category="Components")
    USphereComponent* GoalTrigger;

    UPROPERTY(VisibleAnywhere, Category="Components")
    UStaticMeshComponent* MarkerMesh;

    // Movement towards start when time expires
    UPROPERTY(VisibleAnywhere, Category="Maze|Chase")
    bool bChasingStart = false;

    UFUNCTION()
    void OnGoalOverlap(UPrimitiveComponent* OverlappedComp, AActor* OtherActor,
                       UPrimitiveComponent* OtherComp, int32 OtherBodyIndex,
                       bool bFromSweep, const FHitResult& SweepResult);

    void StartChasingStart();
    void TickChasing(float DeltaSeconds);
};

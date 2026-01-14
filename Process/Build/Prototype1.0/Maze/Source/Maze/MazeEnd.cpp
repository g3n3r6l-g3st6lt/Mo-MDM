#include "MazeEnd.h"

#include "Components/SceneComponent.h"
#include "Components/SphereComponent.h"
#include "Components/StaticMeshComponent.h"
#include "MazeGameMode.h"
#include "MazeActor.h"
#include "MazeGrid.h"
#include "MazeTypes.h"
#include "MazeCharacter.h"
#include "Algo/Reverse.h"

#include "Kismet/GameplayStatics.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Engine/World.h"

AMazeEnd::AMazeEnd()
{
    Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    RootComponent = Root;

    GoalTrigger = CreateDefaultSubobject<USphereComponent>(TEXT("GoalTrigger"));
    GoalTrigger->InitSphereRadius(60.f);
    GoalTrigger->SetupAttachment(RootComponent);
    GoalTrigger->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
    GoalTrigger->SetCollisionResponseToAllChannels(ECR_Ignore);
    GoalTrigger->SetCollisionResponseToChannel(ECC_Pawn, ECR_Overlap);

    MarkerMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MarkerMesh"));
    MarkerMesh->SetupAttachment(RootComponent);
    // Enable collision so the end marker doesn't phase through walls.
    MarkerMesh->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
    MarkerMesh->SetCollisionResponseToAllChannels(ECR_Ignore);
    MarkerMesh->SetCollisionResponseToChannel(ECC_WorldStatic, ECR_Block);

    PrimaryActorTick.bCanEverTick = true;
}

void AMazeEnd::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);

    if (GoalTrigger)
    {
        GoalTrigger->OnComponentBeginOverlap.RemoveAll(this);
        GoalTrigger->OnComponentBeginOverlap.AddDynamic(this, &AMazeEnd::OnGoalOverlap);
    }
}

void AMazeEnd::BeginPlay()
{
    Super::BeginPlay();
    SetActorHiddenInGame(false);

    if (GoalTrigger)
    {
        GoalTrigger->OnComponentBeginOverlap.RemoveAll(this);
        GoalTrigger->OnComponentBeginOverlap.AddDynamic(this, &AMazeEnd::OnGoalOverlap);
    }
}

void AMazeEnd::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);

    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    AMazeGameMode* GM = Cast<AMazeGameMode>(UGameplayStatics::GetGameMode(this));
    if (!GM)
    {
        return;
    }

    // If the run is already finished, stay still.
    if (GM->GetHasFinished())
    {
        return;
    }

    // Let the GameMode control when chasing starts; we only move if bChasingStart is true.
    if (bChasingStart)
    {
        TickChasing(DeltaSeconds);
    }
}

void AMazeEnd::OnGoalOverlap(UPrimitiveComponent* OverlappedComp, AActor* OtherActor,
                             UPrimitiveComponent* OtherComp, int32 OtherBodyIndex,
                             bool bFromSweep, const FHitResult& SweepResult)
{
    if (!OtherActor)
    {
        return;
    }

    // Only react to the player character reaching the end.
    AMazeCharacter* MazeChar = Cast<AMazeCharacter>(OtherActor);
    if (!MazeChar)
    {
        return;
    }

    AMazeGameMode* GM = Cast<AMazeGameMode>(UGameplayStatics::GetGameMode(this));
    if (!GM)
    {
        return;
    }

    // 🔧 FIX: pass the actor that reached the goal (matches NotifyPlayerReachedGoal(AActor*))
    GM->NotifyPlayerReachedGoal(OtherActor);
}

void AMazeEnd::StartChasingStart()
{
    bChasingStart = true;
}

void AMazeEnd::TickChasing(float DeltaSeconds)
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    AMazeGameMode* GM = Cast<AMazeGameMode>(UGameplayStatics::GetGameMode(this));
    if (!GM)
    {
        return;
    }

    // If the run is finished while chasing, stop.
    if (GM->GetHasFinished())
    {
        bChasingStart = false;
        return;
    }

    // 🔧 FIX: use your actual API: GetStartLocation()
    const FVector Target = GM->GetStartLocation();
    const FVector Current = GetActorLocation();
    const FVector ToTarget = Target - Current;

    // Close enough: notify the GameMode that the end has reached the start.
    const float CloseEnoughDistSq = FMath::Square(30.f);
    if (ToTarget.SizeSquared() <= CloseEnoughDistSq)
    {
        bChasingStart = false;
        GM->NotifyEndReachedStart();
        return;
    }

    float Speed = 200.f;

    // Try to base the speed off the player's movement so we stay ~75% of their speed.
    if (ACharacter* PlayerChar = UGameplayStatics::GetPlayerCharacter(this, 0))
    {
        if (UCharacterMovementComponent* Move = PlayerChar->GetCharacterMovement())
        {
            if (Move->MaxWalkSpeed > KINDA_SMALL_NUMBER)
            {
                Speed = Move->MaxWalkSpeed * 0.75f;
            }
        }
    }

    const FVector Dir = ToTarget.GetSafeNormal();
    FVector NewLoc = Current + Dir * Speed * DeltaSeconds;
    NewLoc.Z = Current.Z; // keep original height
    SetActorLocation(NewLoc, true);
}

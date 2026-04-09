#include "TeleportIn.h"
#include "TeleportOut.h"
#include "MazeCharacter.h"

#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/BoxComponent.h"
#include "Kismet/GameplayStatics.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Engine/World.h"
#include "Components/CapsuleComponent.h"

ATeleportIn::ATeleportIn()
{
    Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    RootComponent = Root;

    Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
    Mesh->SetupAttachment(RootComponent);
    Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);

    Trigger = CreateDefaultSubobject<UBoxComponent>(TEXT("Trigger"));
    Trigger->SetupAttachment(RootComponent);
    Trigger->SetBoxExtent(FVector(60.f, 60.f, 100.f));
    Trigger->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
    Trigger->SetCollisionResponseToAllChannels(ECR_Ignore);
    Trigger->SetCollisionResponseToChannel(ECC_Pawn, ECR_Overlap);

    Trigger->OnComponentBeginOverlap.AddDynamic(this, &ATeleportIn::OnTriggerBegin);

    PrimaryActorTick.bCanEverTick = false;
}

void ATeleportIn::BeginPlay()
{
    Super::BeginPlay();

    if (Mesh && TeleportMaterial)
    {
        Mesh->SetMaterial(0, TeleportMaterial);
    }
}

void ATeleportIn::OnTriggerBegin(UPrimitiveComponent* OverlappedComponent, AActor* OtherActor,
                                 UPrimitiveComponent* OtherComp, int32 OtherBodyIndex,
                                 bool bFromSweep, const FHitResult& SweepResult)
{
    UWorld* World = GetWorld();
    if (!World || !OtherActor)
    {
        return;
    }

    // Only react to the maze character.
    AMazeCharacter* Char = Cast<AMazeCharacter>(OtherActor);
    if (!Char)
    {
        return;
    }

    // Simple local cooldown to avoid rapid re-teleports.
    const float Now = World->GetTimeSeconds();
    if (Now - Char->GetLastTeleportTime() < TeleportCooldown)
    {
        return;
    }
    Char->SetLastTeleportTime(Now);

    // Collect all TeleportOut actors in the world.
    TArray<AActor*> AllOuts;
    UGameplayStatics::GetAllActorsOfClass(World, ATeleportOut::StaticClass(), AllOuts);

    if (AllOuts.Num() == 0)
    {
        return;
    }

    // Build a list of valid TeleportOuts (just cast and keep).
    TArray<ATeleportOut*> TeleportOuts;
    for (AActor* A : AllOuts)
    {
        if (ATeleportOut* Out = Cast<ATeleportOut>(A))
        {
            TeleportOuts.Add(Out);
        }
    }

    if (TeleportOuts.Num() == 0)
    {
        return;
    }

    // Pick a random TeleportOut.
    const int32 Index = FMath::RandRange(0, TeleportOuts.Num() - 1);
    ATeleportOut* DestOut = TeleportOuts[Index];
    if (!DestOut)
    {
        return;
    }

    const FVector OutLocation = DestOut->GetActorLocation();

    // Start from the TeleportOut location and search for a nearby free spot.
    FVector DestLocation = OutLocation;

    UCapsuleComponent* Capsule = Char->GetCapsuleComponent();
    if (Capsule)
    {
        const float CapsuleRadius = Capsule->GetScaledCapsuleRadius();
        const float CapsuleHalfHeight = Capsule->GetScaledCapsuleHalfHeight();
        const float OffsetDist = FMath::Max(80.f, CapsuleRadius * 2.5f);

        TArray<FVector> CandidateDirs;
        // Cardinal directions.
        CandidateDirs.Add(FVector(1.f, 0.f, 0.f));
        CandidateDirs.Add(FVector(-1.f, 0.f, 0.f));
        CandidateDirs.Add(FVector(0.f, 1.f, 0.f));
        CandidateDirs.Add(FVector(0.f, -1.f, 0.f));
        // Diagonals.
        CandidateDirs.Add(FVector(1.f, 1.f, 0.f).GetSafeNormal());
        CandidateDirs.Add(FVector(-1.f, 1.f, 0.f).GetSafeNormal());
        CandidateDirs.Add(FVector(1.f, -1.f, 0.f).GetSafeNormal());
        CandidateDirs.Add(FVector(-1.f, -1.f, 0.f).GetSafeNormal());

        bool bFoundOpen = false;
        FCollisionQueryParams Params(SCENE_QUERY_STAT(TeleportInOverlap), false, Char);
        FCollisionShape CapsuleShape = FCollisionShape::MakeCapsule(CapsuleRadius, CapsuleHalfHeight);

        for (const FVector& DirRaw : CandidateDirs)
        {
            const FVector Dir = DirRaw.GetSafeNormal();
            if (Dir.IsNearlyZero())
            {
                continue;
            }

            // Place the capsule center so it stands on the floor near the TeleportOut.
            FVector Candidate = OutLocation + Dir * OffsetDist;
            Candidate.Z = OutLocation.Z + CapsuleHalfHeight + 5.f;

            const bool bBlocked = World->OverlapBlockingTestByChannel(
                Candidate,
                FQuat::Identity,
                ECC_Pawn,
                CapsuleShape,
                Params
            );

            if (!bBlocked)
            {
                DestLocation = Candidate;
                bFoundOpen = true;
                break;
            }
        }

        if (!bFoundOpen)
        {
            // Fallback: place capsule above the TeleportOut and let gravity resolve it.
            DestLocation = OutLocation;
            DestLocation.Z += CapsuleHalfHeight * 2.f + 20.f;
        }
    }
    else
    {
        // No capsule available; just drop at the TeleportOut location with a small lift.
        DestLocation = OutLocation;
        DestLocation.Z += 5.f;
    }

    if (UCharacterMovementComponent* Move = Char->GetCharacterMovement())
    {
        Move->StopMovementImmediately();
        if (Move->MovementMode == MOVE_None)
        {
            Move->SetMovementMode(MOVE_Walking);
        }
    }

    // Teleport without sweep: we've already chosen a non-overlapping spot (or a safe fallback),
    // so we don't need movement-style collision resolution here.
    Char->SetActorLocation(DestLocation, false, nullptr, ETeleportType::TeleportPhysics);
}




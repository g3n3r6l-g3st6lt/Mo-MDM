#include "MazeGameMode.h"
#include "MazeCharacter.h"
#include "MazeStart.h"
#include "MazeEnd.h"
#include "MazePlayerController.h"

#include "Kismet/GameplayStatics.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"

AMazeGameMode::AMazeGameMode()
{
    DefaultPawnClass = AMazeCharacter::StaticClass();
}

void AMazeGameMode::BeginPlay()
{
    Super::BeginPlay();

    UWorld* World = GetWorld();
    if (!World) return;

    // Cache start/end actors and locations
    {
        TArray<AActor*> Starts;
        UGameplayStatics::GetAllActorsOfClass(this, AMazeStart::StaticClass(), Starts);
        if (Starts.Num() > 0)
        {
            MazeStartActor = Cast<AMazeStart>(Starts[0]);
            if (MazeStartActor)
            {
                StartLocation = MazeStartActor->GetActorLocation();
            }
        }
    }

    {
        TArray<AActor*> Ends;
        UGameplayStatics::GetAllActorsOfClass(this, AMazeEnd::StaticClass(), Ends);
        if (Ends.Num() > 0)
        {
            MazeEndActor = Cast<AMazeEnd>(Ends[0]);
            if (MazeEndActor)
            {
                EndLocation = MazeEndActor->GetActorLocation();
            }
        }
    }

    PlacePlayerAtStart();

    GameStartTime = World->GetTimeSeconds();
    bHasFinished = false;
    bStatsFrozen = false;
    FinishStatus = NAME_None;
}

void AMazeGameMode::PlacePlayerAtStart()
{
    UWorld* World = GetWorld();
    if (!World || !MazeStartActor) return;

    APlayerController* PC = UGameplayStatics::GetPlayerController(World, 0);
    if (!PC) return;

    APawn* Pawn = PC->GetPawn();
    if (!Pawn) return;

    Pawn->SetActorLocation(StartLocation);
    Pawn->SetActorRotation(FRotator::ZeroRotator);
}

void AMazeGameMode::IncrementPivotalPointsActivated()
{
    ++NumPivotalPointsActivated;
    if (NumPivotalPointsActivated > NumPivotalPointsTotal)
    {
        NumPivotalPointsActivated = NumPivotalPointsTotal;
    }
}

void AMazeGameMode::FreezeStatsAndFinish(FName InFinishStatus, APawn* InstigatorPawn)
{
    if (bHasFinished)
    {
        return;
    }

    UWorld* World = GetWorld();

    // Snapshot time / overtime BEFORE we mark finished.
    float TimeRemain = GetTimeRemaining();
    FinalTimeRemaining = TNumericLimits<float>::Max();
    OvertimeSeconds = 0.f;

    if (CountdownSeconds > 0)
    {
        if (TimeRemain >= 0.f)
        {
            FinalTimeRemaining = TimeRemain;
            OvertimeSeconds = 0.f;
        }
        else
        {
            FinalTimeRemaining = 0.f;
            OvertimeSeconds = -TimeRemain;
        }
    }

    // Snapshot steps/turns from controller.
    AMazePlayerController* MPC = nullptr;
    if (World)
    {
        MPC = Cast<AMazePlayerController>(UGameplayStatics::GetPlayerController(World, 0));
    }

    if (MPC)
    {
        FinalStepCount = MPC->GetStepCount();
        FinalTurnCount = MPC->GetTurnCount();
        MPC->SetCountersFrozen(true);
    }

    FinalPivotalPointsActivated = NumPivotalPointsActivated;

    bHasFinished = true;
    bStatsFrozen = true;
    FinishStatus = InFinishStatus;

    // Optionally freeze player input.
    if (World)
    {
        if (!InstigatorPawn)
        {
            APlayerController* PC = UGameplayStatics::GetPlayerController(World, 0);
            if (PC)
            {
                InstigatorPawn = PC->GetPawn();
            }
        }

        if (InstigatorPawn)
        {
            if (APlayerController* PC = Cast<APlayerController>(InstigatorPawn->GetController()))
            {
                InstigatorPawn->DisableInput(PC);
            }
        }
    }
}

void AMazeGameMode::NotifyPlayerReachedGoal(AActor* ReachedActor)
{
    if (bHasFinished)
    {
        return;
    }

    APawn* Pawn = Cast<APawn>(ReachedActor);
    const bool bExpired = IsTimeExpired();

    const FName StatusName = bExpired ? FName(TEXT("ElusiveSave")) : FName(TEXT("Goal"));
    FreezeStatsAndFinish(StatusName, Pawn);
}

void AMazeGameMode::NotifyEndReachedStart()
{
    if (bHasFinished)
    {
        return;
    }

    UWorld* World = GetWorld();
    APawn* Pawn = nullptr;

    if (World)
    {
        if (APlayerController* PC = UGameplayStatics::GetPlayerController(World, 0))
        {
            Pawn = PC->GetPawn();
        }
    }

    FreezeStatsAndFinish(FName(TEXT("Singularity")), Pawn);
}

float AMazeGameMode::GetTimeRemaining() const
{
    if (CountdownSeconds <= 0)
    {
        return TNumericLimits<float>::Max();
    }

    if (bStatsFrozen)
    {
        return FinalTimeRemaining;
    }

    const float Now = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.f;
    return float(CountdownSeconds) - (Now - GameStartTime);
}

bool AMazeGameMode::IsTimeExpired() const
{
    return CountdownSeconds > 0 && GetTimeRemaining() <= 0.f && !bHasFinished;
}

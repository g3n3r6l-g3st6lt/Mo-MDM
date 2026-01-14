#include "MazeStatsManagerSubsystem.h"

void UMazeStatsManagerSubsystem::StartRun()
{
    CurrentRun = FMazeRunSummary();
    bRunActive = true;
}

void UMazeStatsManagerSubsystem::FinishRun(bool bInCompleted)
{
    CurrentRun.bCompleted = bInCompleted;
    bRunActive = false;
}

void UMazeStatsManagerSubsystem::NotifyStepTaken()
{
    if (bRunActive)
    {
        ++CurrentRun.Steps;
    }
}

void UMazeStatsManagerSubsystem::NotifyTurnMade()
{
    if (bRunActive)
    {
        ++CurrentRun.Turns;
    }
}

void UMazeStatsManagerSubsystem::TickRun(float DeltaSeconds)
{
    if (bRunActive)
    {
        CurrentRun.ElapsedTime += DeltaSeconds;
    }
}

FMazeRunSummary UMazeStatsManagerSubsystem::GetCurrentSummary() const
{
    return CurrentRun;
}

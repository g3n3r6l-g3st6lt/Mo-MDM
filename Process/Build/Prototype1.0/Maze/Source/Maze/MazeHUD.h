
#pragma once
#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "MazeHUD.generated.h"

class AMazeEnd;
class AActor;
class UFont;

UCLASS()
class MAZE_API AMazeHUD : public AHUD
{
    GENERATED_BODY()

public:
    AMazeHUD();

    virtual void BeginPlay() override;
    virtual void DrawHUD() override;

protected:
    // Developer stats overlay state
    int32 PrevStepCount = 0;
    int32 PrevTurnCount = 0;
    float FrozenProgressPct = 0.f;
    bool bProgressFrozen = false;
    int32 FrozenPivotalActivated = 0;
    int32 FrozenPivotalTotal = 0;
    bool bPivotsFrozen = false;

    UPROPERTY(EditAnywhere, Category="HUD")
    UFont* HudFont = nullptr;

    UPROPERTY(EditAnywhere, Category="HUD")
    FLinearColor TextColor = FLinearColor::White;

    UPROPERTY(EditAnywhere, Category="HUD")
    float TextScale = 1.2f;

    UPROPERTY(EditAnywhere, Category="HUD")
    float BackgroundAlpha = 0.35f;

    UPROPERTY(EditAnywhere, Category="HUD")
    FVector2D BackgroundPadding = FVector2D(16.f, 12.f);

    // === Minimap (canvas-drawn) settings ===
    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    bool bShowMapCanvas = true;

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    FVector2D MapSize = FVector2D(220.f, 220.f);

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    FVector2D MapMargin = FVector2D(20.f, 20.f);

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    FLinearColor MapBackgroundColor = FLinearColor(0.f, 0.f, 0.f, 0.35f);

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    FLinearColor PlayerColor = FLinearColor::White;

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    FLinearColor StartColor = FLinearColor::Green;

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    FLinearColor EndColor = FLinearColor::Red;

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    FLinearColor TeleportInColor = FLinearColor(0.f, 0.6f, 1.f, 1.f);

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    float MarkerSize = 6.f;

    // Static rotation and reflection controls (do NOT follow player automatically)
    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    float MarkerRotationDeg = 0.f;

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    bool bFlipMapHorizontally = false;

    UPROPERTY(EditAnywhere, Category="HUD|MapCanvas")
    bool bFlipMapVertically = false;

    /** Cached maze world bounds in XY for the minimap. */
    FVector2D MazeWorldMin = FVector2D(-1000.f, -1000.f);
    FVector2D MazeWorldMax = FVector2D(1000.f, 1000.f);

    /** Cached MazeEnd actor for the minimap (for moving end marker). */
    UPROPERTY()
    AMazeEnd* MazeEndActor = nullptr;

    /** Cached teleport-in actors for the minimap. */
    UPROPERTY()
    TArray<AActor*> TeleportInActorsCached;

    /** Draws the minimap in the top-right corner using Canvas. */
    void DrawMinimap(const FVector& PlayerLoc, const FVector& StartLoc, const FVector& EndLoc);

    /** Map world XY to minimap UV in [0,1]. */
    FVector2D WorldToMinimap(const FVector& WorldPos) const;
};

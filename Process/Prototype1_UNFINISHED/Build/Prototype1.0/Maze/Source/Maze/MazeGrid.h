#pragma once
#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "MazeTypes.h"
#include "MazeGrid.generated.h"

UCLASS(BlueprintType)
class MAZE_API UMazeGrid : public UObject
{
    GENERATED_BODY()
public:
    UPROPERTY() int32 Rows=0, Cols=0;
    UPROPERTY() TArray<FMazeCell> Cells;

    UFUNCTION(BlueprintCallable) void Generate(const FMazeConfig& InConfig);
    UFUNCTION(BlueprintCallable) TArray<FIntPoint> FindPathBFS(FIntPoint Start, FIntPoint Goal) const;

    UFUNCTION(BlueprintCallable, Category="Maze|Analysis")
    int32 CountOpenSides(int32 C, int32 R) const;

    UFUNCTION(BlueprintCallable, Category="Maze|Analysis")
    bool IsJunction(int32 C, int32 R) const;

    FORCEINLINE bool InBounds(int32 C, int32 R) const { return C>=0 && C<Cols && R>=0 && R<Rows; }
    FORCEINLINE int32 Index(int32 C, int32 R) const { return R*Cols + C; }
};

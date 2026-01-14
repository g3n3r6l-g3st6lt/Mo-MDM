#include "MazeConfigAsset.h"
#include "MazeTypes.h"

FMazeConfig UMazeConfigAsset::ToRuntimeConfig() const
{
    // At the moment this simply returns BaseConfig.
    // In the future you could apply additional runtime adjustments here.
    return BaseConfig;
}

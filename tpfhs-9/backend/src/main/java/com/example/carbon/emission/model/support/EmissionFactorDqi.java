package com.example.carbon.emission.model.support;

public interface EmissionFactorDqi {
    String getEfSourceAuthority();
    String getEfCompletenessScope();
    String getEfDataRegion();
    Integer getEfDataYear();
    String getEfTechApplicability();
    String getEfConversionChain();
    Integer getDqiE1Score();
    Integer getDqiE2Score();
    Integer getDqiE3Score();
    Integer getDqiE4Score();
    Integer getDqiE5Score();
    Integer getDqiE6Score();
}

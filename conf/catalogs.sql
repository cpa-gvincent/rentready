-- RentReady Unity Catalog setup
-- Template variables: ${env}, ${tenant}
-- Substitute in CI or run manually per environment.
--
-- Licensed catalog holds MLS/AVM data under IDX/MLS provenance rules.
-- Public catalog holds government/assessor/licensed-public API data.
--
-- These are the lane boundary the compliance model enforces.

CREATE CATALOG IF NOT EXISTS rentready_${env}_licensed
  COMMENT 'Licensed data lane — MLS (via RESO), licensed AVM. IDX/MLS provenance rules apply.';

CREATE CATALOG IF NOT EXISTS rentready_${env}_public
  COMMENT 'Public data lane — county assessor, gov APIs, licensed public sources. No MLS-derived data.';

CREATE SCHEMA IF NOT EXISTS rentready_${env}_licensed.${tenant}
  COMMENT 'Tenant-isolated schema within the licensed lane.';

CREATE SCHEMA IF NOT EXISTS rentready_${env}_public.${tenant}
  COMMENT 'Tenant-isolated schema within the public lane.';

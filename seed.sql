-- Seed data for LifeOptimization DB
-- Extracted from LifestyleOptimization.pdf

PRAGMA foreign_keys = ON;

-- ============================================================
-- STATUSES (color-coded system from PDF)
-- ============================================================
INSERT INTO statuses (name, color, description) VALUES
    ('Currently Have', 'green', 'Item currently owned/in use'),
    ('Next Purchase', 'blue', 'Next item to buy'),
    ('Eventual Purchase', 'orange', 'Future planned purchase'),
    ('Needs Replacing', 'red', 'Needs replacing or refilling');

-- ============================================================
-- LIFE AREAS
-- ============================================================
INSERT INTO life_areas (name, sort_order) VALUES
    ('Academic', 1),
    ('Career', 2),
    ('Hobbies', 3),
    ('Fitness', 4),
    ('Appearance', 5);

-- ============================================================
-- FASHION CATEGORIES
-- ============================================================
INSERT INTO fashion_categories (name, sort_order) VALUES
    ('Hats', 1),
    ('Tops', 2),
    ('Bottoms', 3),
    ('Shoes', 4),
    ('Accessories', 5);

-- ============================================================
-- FASHION ITEMS (from PDF)
-- ============================================================
INSERT INTO fashion_items (category_id, name, status_id, link, rep_link) VALUES
    -- Hats
    ((SELECT id FROM fashion_categories WHERE name='Hats'),
     'Ami Paris Baseball Cap', 
     (SELECT id FROM statuses WHERE color='blue'),
     NULL, NULL),

    -- Shoes
    ((SELECT id FROM fashion_categories WHERE name='Shoes'),
     'Margiella Gats',
     (SELECT id FROM statuses WHERE color='blue'),
     NULL, NULL);

-- ============================================================
-- SKINCARE ROUTINES
-- ============================================================
INSERT INTO skincare_routines (name, sort_order) VALUES
    ('Morning - Face', 1),
    ('Morning - Body', 2),
    ('Night', 3);

-- ============================================================
-- SKINCARE PRODUCTS (from PDF)
-- ============================================================

-- Morning Face (in order)
INSERT INTO skincare_products (routine_id, name, status_id, step_order, is_wanted) VALUES
    ((SELECT id FROM skincare_routines WHERE name='Morning - Face'),
     'Cetaphil Gentle Exfoliating Salicylic Acid Cleanser',
     (SELECT id FROM statuses WHERE color='green'), 1, 0),

    ((SELECT id FROM skincare_routines WHERE name='Morning - Face'),
     'Advanced Clinical Vitamin C Brightening Serum',
     (SELECT id FROM statuses WHERE color='green'), 2, 0),

    ((SELECT id FROM skincare_routines WHERE name='Morning - Face'),
     'Hims Minoxidil Topical Hair Regrowth Treatment',
     (SELECT id FROM statuses WHERE color='green'), 3, 0),

    ((SELECT id FROM skincare_routines WHERE name='Morning - Face'),
     'Cetaphil Moisturizing Lotion',
     (SELECT id FROM statuses WHERE color='green'), 4, 0),

    ((SELECT id FROM skincare_routines WHERE name='Morning - Face'),
     'Black Girl 30 SPF Sunscreen',
     (SELECT id FROM statuses WHERE color='green'), 5, 0),

    ((SELECT id FROM skincare_routines WHERE name='Morning - Face'),
     'Cover Girl CG Smoother BB Cream (815)',
     (SELECT id FROM statuses WHERE color='green'), 6, 0),

    ((SELECT id FROM skincare_routines WHERE name='Morning - Face'),
     'Carmex Classic Lip Balm',
     (SELECT id FROM statuses WHERE color='green'), 7, 0);

-- Morning Body (in order)
INSERT INTO skincare_products (routine_id, name, status_id, step_order, is_wanted) VALUES
    ((SELECT id FROM skincare_routines WHERE name='Morning - Body'),
     'Every Man Jack Sandal Wood Deodorant',
     (SELECT id FROM statuses WHERE color='green'), 1, 0),

    ((SELECT id FROM skincare_routines WHERE name='Morning - Body'),
     'Cetaphil Moisturizing Lotion',
     (SELECT id FROM statuses WHERE color='green'), 2, 0);

-- Night
INSERT INTO skincare_products (routine_id, name, status_id, step_order, is_wanted) VALUES
    ((SELECT id FROM skincare_routines WHERE name='Night'),
     'Good Molecules Niacinamide Serum',
     (SELECT id FROM statuses WHERE color='green'), 1, 0);

-- Wanted Products
INSERT INTO skincare_products (routine_id, name, status_id, step_order, is_wanted) VALUES
    (NULL,
     'Black Girl Sunscreen',
     (SELECT id FROM statuses WHERE color='blue'), 0, 1);

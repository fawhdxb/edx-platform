""" Journal bundle about page's view """
import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import Http404

from edxmako.shortcuts import render_to_response
from opaque_keys.edx.keys import CourseKey, UsageKey
from lms.djangoapps.courseware.views.views import render_xblock
from lms.djangoapps.commerce.utils import EcommerceService
from openedx.core.djangoapps.catalog.models import CatalogIntegration
from openedx.core.djangoapps.commerce.utils import ecommerce_api_client
from openedx.features.journals.api import get_journal_bundles, get_journals_root_url, fetch_journal_access

XBLOCK_JOURNAL_ACCESS_KEY = "journal_access_for_{username}_{journal_uuid}_{block_id}"
XBLOCK_JOURNAL_ACCESS_KEY_TIMEOUT = 3600


def bundle_about(request, bundle_uuid):
    """
    Journal bundle about page's view.
    """
    bundle = get_journal_bundles(request.site, bundle_uuid=bundle_uuid)
    if not bundle:
        raise Http404
    bundle = bundle[0]  # get_journal_bundles always returns list of bundles
    bundle = extend_bundle(bundle)
    context = {
        'journals_root_url': get_journals_root_url(),
        'discovery_root_url': CatalogIntegration.current().get_internal_api_url(),
        'bundle': bundle,
        'uses_bootstrap': True,
    }
    return render_to_response('journals/bundle_about.html', context)


def render_xblock_by_journal_access(request, usage_key_string):
    """
    Its a wrapper function for lms.djangoapps.courseware.views.views.render_xblock.
    It disables 'check_if_enrolled' flag by checking that user has access on journal.
    """
    user_access = False
    date_format = '%Y-%m-%d'
    journal_uuid = request.GET.get('journal_uuid')
    block_id = UsageKey.from_string(usage_key_string).block_id
    cache_key = XBLOCK_JOURNAL_ACCESS_KEY.format(
        username=request.user.username,
        journal_uuid=journal_uuid,
        block_id=block_id
    )
    journal_access_data = cache.get(cache_key)
    if not journal_access_data:
        journal_access_data = fetch_journal_access(
            request.site,
            request.user,
            block_id=block_id
        )
        cache.set(cache_key, journal_access_data, XBLOCK_JOURNAL_ACCESS_KEY_TIMEOUT)
    for journal_access in journal_access_data:
        if journal_access['journal']['uuid'] == journal_uuid:
            expiration_date = datetime.datetime.strptime(journal_access['expiration_date'], date_format)
            now = datetime.datetime.strptime(datetime.datetime.now().strftime(date_format), date_format)
            if expiration_date >= now:
                user_access = True
    if not user_access:
        raise Http404("User doesn't have access for this journal.")
    return render_xblock(request, usage_key_string, check_if_enrolled=False)


def extend_bundle(bundle):
    """
    Extend the pricing data in journal bundle.
    """
    applicable_seat_types = bundle['applicable_seat_types']
    matching_seats = [
        get_matching_seat(course, applicable_seat_types)
        for course in bundle['courses']
    ]
    # Remove `None`s from above.
    matching_seats = [seat for seat in matching_seats if seat]
    course_skus = [seat['sku'] for seat in matching_seats]
    journal_skus = [journal['sku'] for journal in bundle['journals']]
    all_skus = course_skus + journal_skus
    pricing_data = get_pricing_data(all_skus)
    bundle.update({
        'pricing_data': pricing_data
    })
    return bundle


def get_matching_seat(course, seat_types):
    """ Filtered out the course runs on the bases of applicable_seat_types """
    for course_run in course['course_runs']:
        for seat in course_run['seats']:
            if seat['type'] in seat_types:
                return seat


def get_pricing_data(skus):
    """
    Get the pricing data from ecommerce for given skus.
    """
    user = User.objects.get(username=settings.ECOMMERCE_SERVICE_WORKER_USERNAME)
    api = ecommerce_api_client(user)
    pricing_data = api.baskets.calculate.get(sku=skus, is_anonymous=True)
    discount_value = float(pricing_data['total_incl_tax_excl_discounts']) - float(pricing_data['total_incl_tax'])
    ecommerce_service = EcommerceService()
    purchase_url = ecommerce_service.get_checkout_page_url(*skus)
    pricing_data.update({
        'is_discounted': pricing_data['total_incl_tax'] != pricing_data['total_incl_tax_excl_discounts'],
        'discount_value': discount_value,
        'purchase_url': purchase_url,
    })
    return pricing_data
